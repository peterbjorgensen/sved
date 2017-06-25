#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Vim global plugin for synchronizing vim and evince with synctex
# Last Change:  2016 November 06
# Maintainer:   Peter B. Jørgensen <peterbjorgensen@gmail.com>
# License:  This file is licensed under the BEER-WARE license rev 42.
#   THE BEER-WARE LICENSE" (Revision 42):
#   <peterbjorgensen@gmail.com> wrote this file.
#   As long as you retain this notice you can do whatever you want with this stuff.
#   If we meet some day, and you think this stuff is worth it, you can buy me a beer in return.

import os
import dbus
from traceback import print_exc
import glob
import time
import urllib.parse
import json
import logging

class EvinceSync(object):
    """A DBus proxy for an Evince Window. Base class."""

    def __init__(self):
        self.bus = None
        self.daemon = None

        logging.debug("connect_bus: connecting to dbus")
        self.bus = dbus.SessionBus()

class EvinceSyncSource(EvinceSync):
    """Handles DBus SyncSource signals """
    def __init__(self):
        super(EvinceSyncSource, self).__init__()

        self.bus.add_signal_receiver(self.on_sync_source,
                signal_name = "SyncSource",
                dbus_interface = "org.gnome.evince.Window")

    def on_sync_source(self, input_file, source_link, timestamp):
        """Handle SyncSource signal from evince.Window"""
        logging.debug( "on_sync_source received: %s %s"
                % (input_file, source_link) )
        # Check for file:// in uri
        if not input_file.startswith("file://"):
            logging.debug("on_sync_source: 'file://' not found in input_file")
            return
        # Unquote string and escape quotation marks
        source = urllib.parse.unquote(input_file[len("file://"):]).replace("\"", "\\\"")
        line = source_link[0]
        cmd = """execute "edit! +%d " . fnameescape("%s")""" % (line, source)
        logging.debug("on_sync_source: Executing %s" % (cmd))
        sys.stdout.write((json.dumps(["ex", cmd]) + "\n"))
        sys.stdout.flush()

class EvinceSyncView(EvinceSync):
    """Handle chain of operations for forward synchronisation"""
    def __init__(self, done_callback=None):
        super(EvinceSyncView, self).__init__()

        self.done_callback = done_callback
        self.bus.add_signal_receiver(self.on_document_load,
               signal_name = "DocumentLoaded",
               dbus_interface = "org.gnome.evince.Window",
               sender_keyword = "sender")
        self.evince_name = None
        self.sync_queue = []

        self.pdf_uri = None
        self.source_file = None
        self.curpos = None


    def sync_view(self, pdf_uri, source_file, curpos):
        """Forward sync Evince with source_file and curpos (line,column)"""
        logging.debug("sync_view: Forward syncing")
        self.connect_daemon()
        pdf_uri = "file://" + urllib.parse.quote(pdf_uri)
        self.pdf_uri = pdf_uri
        self.source_file = source_file
        self.curpos = curpos

        logging.debug("sync_view: calling FindDocument on %s" % self.pdf_uri)
        self.daemon.FindDocument(self.pdf_uri, True,
            dbus_interface="org.gnome.evince.Daemon",
            reply_handler=self.handle_find_document_reply,
            error_handler=self.handle_find_document_error )

    def connect_daemon(self):
        """Establish connection to Evince dbus Daemon"""
        logging.debug("connect_daemon: connecting to Evince daemon")
        self.daemon = self.bus.get_object(
                    "org.gnome.evince.Daemon",
                    "/org/gnome/evince/Daemon")

    def handle_find_document_reply(self, evince_name):
        logging.debug("handle_find_document_reply: Find document reply: "
                + evince_name)
        if (evince_name != "") and (evince_name is not None):
            self.evince_name = evince_name
            ev = self.bus.get_object(evince_name, "/org/gnome/evince/Evince")
            ev.GetWindowList(reply_handler = self.handle_get_window_list_reply,
                            error_handler = self.handle_get_window_list_error,
                            dbus_interface = "org.gnome.evince.Application")

    def on_document_load(self, uri, sender=None):
        """Handle DocumentLoaded signal from evince.Window"""
        logging.debug("on_document_load received: %s, %s" % (uri, sender))
        if uri == self.pdf_uri:
            self.handle_find_document_reply(sender)
        else:
            logging.debug("on_document_load pdf uri does not match target %s"
                    % self.pdf_uri)

    def handle_find_document_error(self, err):
        logging.debug("handle_find_document_error: "
                + err.get_dbus_message())

    def handle_get_window_list_reply(self, window_list):
        logging.debug("handle_get_window_list_reply: " + str(window_list))
        if len(window_list) > 0:
            window_path = window_list[0]
            window_proxy = self.bus.get_object(self.evince_name, window_path)
            logging.debug("handle_get_window_list_reply: calling SyncView %s %s" %
                (self.source_file, self.curpos) )
            window_proxy.SyncView(self.source_file, self.curpos, 0,
                        dbus_interface="org.gnome.evince.Window")
            logging.debug("SyncView done")
            if self.done_callback:
                self.done_callback()
        else:
            logging.debug("handle_get_window_list_reply: empty window list")


    def handle_get_window_list_error(self, err):
        logging.debug("handle_get_window_list_error: "
                + err.get_dbus_message())


def sync_view(pdf_path, input_path, curpos):
    sved_daemon = EvinceSyncView(done_callback = quit_callback)
    sved_daemon.sync_view(pdf_path, input_path, curpos)
    return False

def start_source_sync_daemon():
    sved_daemon = EvinceSyncSource()

def quit_callback():
    GObject.timeout_add(100, loop.quit)


if __name__ == "__main__":
    import sys
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GObject

    if False: # Switch to enable debugging to file
        logging.basicConfig(
                format='%(asctime)s %(levelname)s:%(message)s',
                filename='sved_%d.log' % os.getpid(),
                level=logging.DEBUG)
        logging.debug("stdout encoding is %s" % sys.stdout.encoding)

    dbus.mainloop.glib.threads_init()
    DBusGMainLoop(set_as_default=True)

    loop = GObject.MainLoop()

    if len(sys.argv) == 5:
        # SyncView and quit
        pdf = sys.argv[1]
        curpos = (int(sys.argv[2]), int(sys.argv[3]))
        path_source = sys.argv[4]
        GObject.timeout_add(10, sync_view, pdf, path_source, curpos)
    elif len(sys.argv) == 1:
        # Wait for sync source forever
        start_source_sync_daemon()

    loop.run()
    logging.debug("Exited mainloop")
    sys.exit(0)


