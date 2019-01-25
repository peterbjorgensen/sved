#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Vim global plugin for synchronizing vim and evince with synctex
# Last Change:  2017 June 26
# Maintainer:   Peter B. Jørgensen <peterbjorgensen@gmail.com>
# License:  This file is licensed under the BEER-WARE license rev 42.
#   THE BEER-WARE LICENSE" (Revision 42):
#   <peterbjorgensen@gmail.com> wrote this file.
#   As long as you retain this notice you can do whatever you want with this stuff.
#   If we meet some day, and you think this stuff is worth it, you can buy me a beer in return.

import os
import urllib.parse
import json
import logging
import sys
import dbus

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib


class EvinceSyncSourceCommon():
    """Handles DBus SyncSource signals """
    def __init__(self):
        logging.debug("connect_bus: connecting to dbus")
        self.bus = dbus.SessionBus()

        self.bus.add_signal_receiver(
            self.on_sync_source,
            signal_name="SyncSource",
            dbus_interface="org.gnome.evince.Window")

    def on_sync_source(self, input_file, source_link, _):
        """Handle SyncSource signal (input_file, source_link, timestamp)
        from evince.Window"""
        logging.debug("on_sync_source received: %s %s",
                      input_file, source_link)
        # Check for file:// in uri
        if not input_file.startswith("file://"):
            logging.debug("on_sync_source: 'file://' not found in input_file")
            return
        # Unquote string and escape quotation marks
        source = urllib.parse.unquote(input_file[len("file://"):]).replace("\"", "\\\"")
        line = source_link[0]
        # if the file is already open, scan to the right line
        # else open a new buffer
        # E94 = No matching buffer
        # E37 = Unsaved changes
        cmd = r"""
        silent
        | try
            | try
                | execute 'buffer +{line} ' . fnameescape("{file}")
            | catch /^Vim\%((\a\+)\)\=:E37/
                | execute 'sbuffer +{line} ' . fnameescape("{file}")
            | endtry
        | catch /^Vim\%((\a\+)\)\=:E94/
            | try
                | execute 'edit +{line} ' . fnameescape("{file}")
            | catch /^Vim\%((\a\+)\)\=:E37/
                | execute 'split +{line} ' . fnameescape("{file}")
            | endtry
        | endtry
        """.format(line=line, file=source)
        logging.debug("on_sync_source: Executing %s", cmd)
        self.execute_command(cmd)

    def execute_command(self, command):
        """Executes vim/nvim command"""
        raise NotImplementedError("Must be implemented specifically for vim/nvim")


class EvinceSyncSourceVim(EvinceSyncSourceCommon):
    """EvinceSyncSourceVim
    Source synchronization deamon for Vim 8 or later"""
    def execute_command(self, command):
        sys.stdout.write((json.dumps(["ex", command]) + "\n"))
        sys.stdout.write((json.dumps(["ex", "redraw"]) + "\n"))
        sys.stdout.flush()

class EvinceSyncSourceNeovim(EvinceSyncSourceCommon):
    """EvinceSyncSourceNeovim
    Source synchronization deamon for Neovim"""
    def __init__(self):
        super(EvinceSyncSourceNeovim, self).__init__()

        logging.debug("importing neovim module")
        import neovim
        logging.debug("attaching to neovim through stdio")
        self.nvim = neovim.attach("stdio")

    def execute_command(self, command):
        self.nvim.command(command)

class EvinceSyncView():
    URI_UNRESERVED_MARKS = "-_.!~*'()" # RFC 2396 Sec 2.3
    URI_UNRESERVED_PATH_COMPONENT = ":@&=+$," # RFC 2396 Sec 3.3
    URI_PATH_SAFE_CHARACTERS = \
        URI_UNRESERVED_MARKS + URI_UNRESERVED_PATH_COMPONENT + "/"
    """Handle chain of operations for forward synchronisation"""
    def __init__(self, done_callback=None):
        logging.debug("connect_bus: connecting to dbus")
        self.bus = dbus.SessionBus()
        self.daemon = None

        self.done_callback = done_callback
        self.bus.add_signal_receiver(
            self.on_document_load,
            signal_name="DocumentLoaded",
            dbus_interface="org.gnome.evince.Window",
            sender_keyword="sender")
        self.evince_name = None

        self.pdf_uri = None
        self.source_file = None
        self.curpos = None


    def sync_view(self, pdf_uri, source_file, curpos):
        """Forward sync Evince with source_file and curpos (line,column)"""
        logging.debug("sync_view: Forward syncing")
        self.connect_daemon()
        pdf_uri = "file://" + urllib.parse.quote(pdf_uri, safe=self.URI_PATH_SAFE_CHARACTERS)
        self.pdf_uri = pdf_uri
        self.source_file = source_file
        self.curpos = curpos

        logging.debug("sync_view: calling FindDocument on %s", self.pdf_uri)
        self.daemon.FindDocument(
            self.pdf_uri,
            True,
            dbus_interface="org.gnome.evince.Daemon",
            reply_handler=self.handle_find_document_reply,
            error_handler=self.handle_find_document_error)

    def connect_daemon(self):
        """Establish connection to Evince dbus Daemon"""
        logging.debug("connect_daemon: connecting to Evince daemon")
        self.daemon = self.bus.get_object(
            "org.gnome.evince.Daemon",
            "/org/gnome/evince/Daemon")

    def handle_find_document_reply(self, evince_name):
        """Handle find document reply by calling
        GetWindowList on the returned Evince instance"""
        logging.debug("handle_find_document_reply: Find document reply: %s",
                      evince_name)
        if (evince_name != "") and (evince_name is not None):
            self.evince_name = evince_name
            ev_obj = self.bus.get_object(evince_name, "/org/gnome/evince/Evince")
            ev_obj.GetWindowList(
                reply_handler=self.handle_get_window_list_reply,
                error_handler=self.handle_get_window_list_error,
                dbus_interface="org.gnome.evince.Application")

    def on_document_load(self, uri, sender=None):
        """Handle DocumentLoaded signal from evince.Window"""
        logging.debug("on_document_load received: %s, %s", uri, sender)
        if uri == self.pdf_uri:
            self.handle_find_document_reply(sender)
        else:
            logging.debug(
                "on_document_load pdf uri does not match target %s",
                self.pdf_uri)

    def handle_find_document_error(self, err):
        """Handle errors occured during find_document"""
        error = err.get_dbus_message()
        logging.debug("handle_find_document_error: %s",
                      error)
        print("Could not find document: %s" % error)
        sys.exit(1)

    def handle_get_window_list_reply(self, window_list):
        """Handle window_list_reply by calling SyncView on
        the first entry in the window list"""
        logging.debug("handle_get_window_list_reply: %s", str(window_list))
        if window_list:
            window_path = window_list[0]
            window_proxy = self.bus.get_object(self.evince_name, window_path)
            logging.debug(
                "handle_get_window_list_reply: calling SyncView %s %s",
                self.source_file,
                self.curpos)
            window_proxy.SyncView(
                self.source_file,
                self.curpos,
                0,
                dbus_interface="org.gnome.evince.Window")
            logging.debug("SyncView done")
            if self.done_callback:
                self.done_callback()
        else:
            logging.debug("handle_get_window_list_reply: empty window list")


    def handle_get_window_list_error(self, err):
        """Handle errors in reply to get_window_list"""
        error = err.get_dbus_message()
        logging.debug("handle_get_window_list_error: %s", error)
        print("Could not find document: %s" % error)
        sys.exit(1)


def start_source_sync_daemon(is_neovim):
    """Start source sync daemon in neovim (True) or vim (False) mode"""
    if is_neovim:
        EvinceSyncSourceNeovim()
    else:
        EvinceSyncSourceVim()

def main(enable_logging=False):
    """Main function: setup dbus mainloop and call sync_view
    or start source_sync_daemon depending on sys.argv arguments"""
    if enable_logging:
        logging.basicConfig(
            format='%(asctime)s %(levelname)s:%(message)s',
            filename='sved_%d.log' % os.getpid(),
            level=logging.DEBUG)
        logging.debug("stdout encoding is %s", sys.stdout.encoding)

    logging.debug("got following arguments %s", " ".join(sys.argv))

    dbus.mainloop.glib.threads_init()
    DBusGMainLoop(set_as_default=True)
    glib_main_loop = GLib.MainLoop()

    if len(sys.argv) == 5:
        # SyncView and quit
        pdf = sys.argv[1]
        curpos = (int(sys.argv[2]), int(sys.argv[3]))
        path_source = sys.argv[4]

        def quit_callback():
            GLib.timeout_add(100, glib_main_loop.quit)
        def sync_view(pdf_path, input_path, curpos):
            sved_daemon = EvinceSyncView(done_callback=quit_callback)
            sved_daemon.sync_view(pdf_path, input_path, curpos)
            return False

        GLib.timeout_add(10, sync_view, pdf, path_source, curpos)
    elif len(sys.argv) == 2:
        is_neovim = bool(int(sys.argv[1]))
        # Wait for sync source forever
        start_source_sync_daemon(is_neovim)
    else:
        raise Exception("Invalid number of command line arguments: got %s" % " ".join(sys.argv))

    glib_main_loop.run()
    logging.debug("Exited mainloop")
    sys.exit(0)

if __name__ == "__main__":
    main(enable_logging=os.environ.get("SVED_DEBUG"))
