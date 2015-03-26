#!/usr/bin/env python3

import sys
import os
import os.path as path
import subprocess
import shutil
import argparse


XCLIP = shutil.which('xclip')
XDOTOOL = shutil.which('xdotool')
DMENU = shutil.which('dmenu')
PASS = shutil.which('pass')
STORE = path.normpath(path.expanduser('~/.password-store'))


def check_output(args):
    output = subprocess.check_output(args)
    output = output.decode('utf-8').split('\n')
    return output


def dmenu(choices, args=[], path=DMENU):
    """
    Displays a menu with the given choices by executing dmenu
    with the provided list of arguments. Returns the selected choice
    or None if the menu was aborted.
    """
    dmenu = subprocess.Popen([path] + args,
                             stdin=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             stdout=subprocess.PIPE)
    choice_lines = '\n'.join(map(str, choices))
    choice, errors = dmenu.communicate(choice_lines.encode('utf-8'))
    if dmenu.returncode not in [0, 1]:
        print("dmenu returned {} and error:\n{}"
              .format(dmenu.returncode, errors.decode('utf-8')),
              file=sys.stderr)
        sys.exit(1)
    choice = choice.decode('utf-8').rstrip()
    return choice if choice in choices else None


def collect_choices(store):
    choices = []
    for dirpath, dirs, files in os.walk(store, followlinks=True):
        dirsubpath = dirpath[len(store):].lstrip('/')
        for f in files:
            if f.endswith('.gpg'):
                choices += [os.path.join(dirsubpath, f[:-4])]
    return choices


def xdotool(entries, press_return, delay):
    getwin = "getactivewindow"
    commands = [c for e in entries[:-1] for c in (
        "type --clearmodifiers --delay '{}' '{}'".format(delay, e),
        "key --clearmodifiers --delay '{}' Tab".format(delay))]
    commands += ["type --clearmodifiers --delay '{}' '{}'".format(delay,
                                                                  entries[-1])]
    if press_return:
        commands += ["key --clearmodifiers --delay '{}' Return".format(delay)]
    for command in commands:
        subprocess.check_output([XDOTOOL, "-"],
                                input='{}\n{}'.format(getwin, command),
                                universal_newlines=True)


def get_pass_output(gpg_file, path=PASS, store=STORE):
    environ = os.environ.copy()
    environ["PASSWORD_STORE_DIR"] = store
    passp = subprocess.Popen([path, gpg_file], env=environ,
                             stderr=subprocess.PIPE,
                             stdout=subprocess.PIPE)
    output, err = passp.communicate()
    if passp.returncode != 0:
        print("pass returned {} and error:\n{}".format(
            passp.returncode, err.decode('utf-8')), file=sys.stderr)
        sys.exit(1)
    output = output.decode('utf-8').split('\n')
    password = None
    if len(output) > 0:
        password = output[0]
    user = None
    if len(output) > 1:
        userline = output[1].split()
        if len(userline) > 1:
            # assume the first 'word' after some prefix is the username
            # TODO any better, reasonable assumption for lines
            # with more 'words'?
            user = userline[1]
        elif len(userline) == 1:
            # assume the user has no 'User: ' prefix or similar
            user = userline[0]
    return user, password


def main():
    parser = argparse.ArgumentParser(
        description="A dmenu frontend to pass." +
        " All passed arguments not listed below, are passed to dmenu." +
        " Requires xclip in default mode.")
    parser.add_argument('-t', '--type', dest='autotype', action='store_true',
                        help='Use xdotool to type the username and/or' +
                        ' password into the currently active window.')
    parser.add_argument('-r', '--return', dest='press_return',
                        action='store_true',
                        help='Presses "Return" after typing. Forces --type.')
    parser.add_argument('-u', '--user', dest="get_user", action='store_true',
                        help='Copy/type the username.')
    parser.add_argument('-P', '--pw', dest="get_pass", action='store_true',
                        help='Copy/type the password. Default, use -u -P to ' +
                        'copy both username and password.')
    parser.add_argument('-s', '--store', dest="store", default=STORE,
                        help='The path to the pass password store.\n' +
                        'Defaults to ~/.password-store')
    parser.add_argument('-d', '--delay', dest="xdo_delay", default=None,
                        help='The delay between keystrokes. ' +
                        'Defaults to xdotool\'s default.')
    parser.add_argument('-B', '--pass', dest="pass_bin", default=PASS,
                        help='The path to the pass binary. ' +
                        ('Cannot find a default path to pass, ' +
                         'you must provide this option.'
                         if PASS is None else 'Defaults to ' + PASS))
    parser.add_argument('-D', '--dmenu', dest="dmenu_bin", default=DMENU,
                        help='The path to the dmenu binary. ' +
                        ('Cannot find a default path to dmenu, ' +
                         'you must provide this option.'
                         if DMENU is None else 'Defaults to ' + DMENU))

    args, unknown_args = parser.parse_known_args()

    if not args.get_user and not args.get_pass:
        args.get_user = True

    if args.press_return:
        args.autotype = True

    dmenu_opts = ["-p"]

    if args.pass_bin is None:
        print("You need to provide a path to pass. See -h for more.",
              file=sys.stderr)

    if args.dmenu_bin is None:
        print("You need to provide a path to dmenu. See -h for more.",
              file=sys.stderr)

    if args.autotype:
        if XDOTOOL is None:
            print("You need to install xdotool.", file=sys.stderr)
            sys.exit(1)
        if args.press_return:
            dmenu_opts += ["enter"]
        else:
            dmenu_opts += ["type"]
    else:
        if XCLIP is None:
            print("You need to install xclip.", file=sys.stderr)
            sys.exit(1)
        dmenu_opts += ["copy"]

    dmenu_opts += unknown_args
    # make sure the password store exists
    if not os.path.isdir(args.store):
        print("The password store location, " + args.store +
              ", does not exist.", file=sys.stderr)
        sys.exit(1)
    if shutil.which(args.pass_bin) is None:
        print("The pass binary, {}, does not exist or is not executable."
              .format(args.pass_bin), file=sys.stderr)
        sys.exit(1)

    choices = collect_choices(args.store)
    choice = dmenu(choices, dmenu_opts, args.dmenu_bin)
    # Check if user aborted
    if choice is None:
        sys.exit(0)
    user, pw = get_pass_output(choice, args.pass_bin, args.store)

    info = []
    if args.get_user and user is not None:
        info += [user]
    if args.get_pass and pw is not None:
        info += [pw]

    if args.autotype:
        xdotool(info, args.press_return, args.xdo_delay)
    else:
        clip = '\n'.join(info)
        xclip = subprocess.Popen([XCLIP], stdin=subprocess.PIPE)
        xclip.communicate(clip.encode('utf-8'))
        xclip.wait()


if __name__ == "__main__":
    main()
