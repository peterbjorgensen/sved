# Description
SVED is a Vim plugin enabling synctex synchronization
support for Vim and Evince through DBus.
Vim/gVim and Neovim are supported

# Requirements
SVED requires Neovim or Vim 8 (for asynchronous job support) 
or later, Evince version 3.0 or later and the python3
command available in your PATH.
You need the Python `pygobject` package as well as `dbus-python`, which are most likely already installed in your system.
For Neovim you also need the `pynvim` Python package. Install with `pip install pynvim` or through your package manager.
Vim does not need to be compiled with python support.

# Installation
## Pathogen Install
Do:
`git clone https://github.com/peder2tm/sved.git ~/.vim/bundle/`
and create a binding to do forward synchronization:
`nmap <F4> :call SVED_Sync()<CR>`

## Manual Install
Place both files of the plugin in `~/.vim/ftplugin/`
and create a binding to do forward synchronization:
`nmap <F4> :call SVED_Sync()<CR>`

# Forward Synchronization
The plugin searches for a file called `*.latexmain` (like vim-latex-suite) or
`*.synctex.gz` in order to do forward synchronization.  If your main file of the
latex project is called main.tex, you can create an empty file called
main.tex.latexmain and the script will use this to find the main pdf.  Compile
the project with: `pdflatex --synctex=1 main.tex`
Then forward synchronization should work.

# Backward Synchronization
When you have a tex file open in Vim, ctrl-click in the Evince pdf and Vim will
jump to the corresponding point. Vim will also jump to files you do not
currently have open.

# Older Vim installations
The plugin requires Vim 8 or later because it makes use of the asynchronous job
feature introduced in Vim 8 to do backward synchronization. If you are using an
older version of Vim, check out the version 1.0 release here on Github, which
supports older versions of Vim, but does only work with gVim (not console Vim),
because it needs the GTK loop of gVim to catch the bacward sunchronization
signal from DBus.
