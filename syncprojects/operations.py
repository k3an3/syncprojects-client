import datetime
import json
import logging
import subprocess
from concurrent.futures.thread import ThreadPoolExecutor
from os import listdir
from os.path import join, isfile, islink, isdir
from pathlib import Path
from typing import Dict

import timeago
from progress.bar import IncrementalBar

from syncprojects import config as config
from syncprojects.utils import print_hr, current_user, format_time, validate_changelog, prompt_to_exit, handle_link, \
    get_patched_progress, get_input_choice

logger = logging.getLogger('syncprojects.operations')


def copy(dir_name, src, dst, update=True):
    copy_tree(join(src, dir_name), join(dst, dir_name), update=update)


def changelog(directory):
    changelog_file = join(config.SOURCE, directory, "changelog.txt")
    if not isfile(changelog_file):
        logger.info("Creating changelog...")
        divider = print_hr("*", config.CHANGELOG_HEADER_WIDTH)
        changelog_header = divider + "\n*{}*\n".format(
            ("CHANGELOG: " + directory).center(config.CHANGELOG_HEADER_WIDTH - 2)) + divider
        with open(changelog_file, "w") as f:
            f.write(changelog_header)
    print("Add a summary of the changes you made to {}, then save and close Notepad.".format(directory))
    user = current_user()
    header = "\n\n-- {}: {} --\n".format(user, format_time())
    header += "=" * (len(header) - 3) + "\n\n"
    with open(changelog_file, "r+") as f:
        lines = f.readlines()
        lines.insert(3, header)
        f.seek(0)
        f.writelines(lines)
    subprocess.run([config.NOTEPAD, changelog_file])
    while err := validate_changelog(changelog_file):
        logger.warning("Error! Improper formatting in changelog. Please correct it:\n")
        logger.warning(err)
        subprocess.run([config.NOTEPAD, changelog_file])


def check_wants():
    wants_file = join(config.DEFAULT_DEST, 'remote.wants')
    if isfile(wants_file):
        try:
            logger.debug("Loading wants file...")
            with open(wants_file) as f:
                wants = json.load(f)
                logger.debug(f"Wants file contains: {wants}")
                if wants.get('user') != current_user():
                    logger.debug("Wants are not from current user, fetching")
                    Path(wants_file).unlink()
                    return wants['projects']
                else:
                    logger.debug("Wants are from current user, not fetching...")
        except Exception as e:
            logger.debug("Exception in wants:" + str(e))
    else:
        logger.debug("Didn't find wants file. Skipping...")
    return []


def handle_new_song(song_name, remote_hs):
    if song_name not in remote_hs.content:
        for song in remote_hs.content.keys():
            if song_name.lower() == song.lower():
                logger.error(
                    f"\nERROR: Your song is named \"{song_name}\", but a similarly named song \"{song}\" "
                    f"already exists remotely. Please check your spelling/capitalization and try again.")
                # TODO
                # unlock(project, api_client)
                prompt_to_exit()


progress = get_patched_progress()


def copy_tree(src, dst, preserve_mode=1, preserve_times=1,
              preserve_symlinks=0, update=0, verbose=1, dry_run=0,
              progress=True, executor=None, single_depth=False):
    from distutils.file_util import copy_file
    from distutils.dir_util import mkpath

    if not executor:
        executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)

    names = listdir(src)

    if not dry_run:
        mkpath(dst, verbose=verbose)

    outputs = []
    if progress:
        bar = IncrementalBar("Copying", max=len(names))
    for n in names:
        src_name = join(src, n)
        dst_name = join(dst, n)

        if progress:
            bar.next()
        if n.startswith('.nfs'):
            # skip NFS rename files
            continue

        if preserve_symlinks and islink(src_name):
            outputs.append(executor.submit(handle_link, src_name, dst_name, verbose, dry_run))

        elif isdir(src_name) and not single_depth:
            outputs.append(
                executor.submit(
                    copy_tree, src_name, dst_name, preserve_mode,
                    preserve_times, preserve_symlinks, update,
                    verbose=verbose, dry_run=dry_run, progress=False, executor=executor))
        else:
            executor.submit(
                copy_file, src_name, dst_name, preserve_mode,
                preserve_times, update, verbose=verbose,
                dry_run=dry_run)
            outputs.append(dst_name)
    if progress:
        bar.finish()
    return outputs


def check_out(project, api_client, hours=8):
    until = (datetime.datetime.now() + datetime.timedelta(hours=hours)).timestamp()
    lock(project, api_client, "checkout", until)


def get_lock_status(locked: Dict):
    if 'id' in locked:
        return locked['id']
    if locked['status'] == 'locked':
        # A null until means this is a sync/song checkout, not a project checkout
        # at least for now
        if not locked.get('until'):
            if not locked['locked_by'] == "self":
                logger.debug(
                    f"Locked by {locked['locked_by']} since {datetime.datetime.fromtimestamp(float(locked['since'])).isoformat()})")
        elif not locked['locked_by'] == "self":
            checked_out_until = datetime.datetime.fromtimestamp(float(locked['until']))
            if ((checked_out_until - datetime.datetime.now()).total_seconds() / 3600) > 0:
                logger.debug(
                    f"Currently checked out by {locked['locked_by']} for"
                    f"{timeago.format(checked_out_until, datetime.datetime.now())}"
                    f"or until it's checked in.")
            else:
                logger.warning("Expiring lock, as expire time has passed. Server should have cleaned this up.")
        else:
            logger.debug("Hit lock() fallthrough case!")


def lock(project, api_client, reason: str = "sync", duration: datetime.datetime = None):
    locked = api_client.lock(project, reason=reason, until=duration)
    logger.debug(f"Got lock response {locked}")
    if 'id' in locked:
        return locked['id']
    if locked['status'] == 'locked':
        if not locked.get('until'):
            logger.warning(f"{project['name']}: A sync is still running or did not complete successfully.")
            if not locked['locked_by'] == "self":
                logger.warning(
                    f"WARNING: It looks like {locked['locked_by']} is/was trying to sync (since {datetime.datetime.fromtimestamp(float(locked['since'])).isoformat()})... maybe talk to them before overriding?")
            choices = ("Try again", "override", "exit")
            choice = None
            while choice not in choices:
                choice = get_input_choice(choices)
            if choice == "exit":
                logger.info("Bailing!")
                raise SystemExit
            elif choice == "override":
                api_client.lock(project, force=True)
            elif choice == "Try Again":
                lock(project, api_client, reason, duration)
        elif not locked['locked_by'] == "self":
            checked_out_until = datetime.datetime.fromtimestamp(float(locked['until']))
            if ((checked_out_until - datetime.datetime.now()).total_seconds() / 3600) > 0:
                logger.info(
                    f"The project is currently checked out by {locked['locked_by']} for "
                    f"{timeago.format(checked_out_until, datetime.datetime.now())} hours "
                    f"or until it's checked in.")
                logger.info("Bailing!")
                raise SystemExit
            else:
                logger.debug("Expiring lock as time has passed. Server should have cleaned this up.")
        else:
            logger.debug("Hit lock() fallthrough case!")


def unlock(project, api_client):
    unlocked = api_client.unlock(project)
    if unlocked.get("result") == "success":
        logger.debug("Successful unlock")
    elif unlocked['status'] == 'locked':
        logger.warning(f"WARNING: The studio could not be unlocked: {unlocked}")
    elif unlocked['status'] == 'unlocked':
        logger.warning(f"WARNING: The studio was already unlocked: {unlocked}")
