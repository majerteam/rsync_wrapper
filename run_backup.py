#!/usr/bin/python3

"""
Run rsync backup and log all data.

Config file mandatory.

Places for config file
-----------------------

File must be named run_backup.rc an can exist in any xdg config dirs,
or in the user's home

Example config file
-----------------------

[main_backup]
host=192.168.12.26
src_dir=/dir/to/sync/
dst_dir=/mirror/of/dir
logbase=/place/where/i/log
"""


import collections
import configparser
import datetime
import logging
import os
import subprocess
import sys


StreamHandler = getattr(logging, 'StreamHandler', None)
if not StreamHandler:
    # depends on Python version?
    import logging.handlers
    StreamHandler = logging.handlers.StreamHandler


# holds config

Context = collections.namedtuple(
    'BackupContext',
    (
        'host',
        'src_dir',
        'dst_dir',
        'logfile',
        'log_out_fd',
        'log_err_fd',
        'log_ret_fd',
    )
)


def backup(context, logger):
    """
    Actually run rsync
    """
    command = [
        'rsync',
        '-avz',
        '--delete',
        '{context.host}:{context.src_dir}'.format(context=context),
        '{context.dst_dir}'.format(context=context),
    ]

    logger.info("running command {0}".format(' '.join(command)))
    for desc, fname in (
        ("python log", context.logfile),
        ("stdout", context.log_out_fd.name),
        ("stderr", context.log_err_fd.name),
        ("return code", context.log_ret_fd.name),
            ):
        logger.info("{0} goes to {1}".format(desc, fname))

    process = subprocess.Popen(
        command,
        stdout=context.log_out_fd,
        stderr=context.log_err_fd,
    )
    process.wait()
    returncode = process.returncode

    if returncode == 0:
        logfn = logger.info
    else:
        logfn = logger.critical

    context.log_ret_fd.write('{0}\n'.format(process.returncode))
    logfn('{0[0]} exited with status {1}'.format(command, returncode))


def _config_file():
    """
    Locate the config file or raises Exception
    """
    config_fname = 'run_backup.rc'
    candidates = []
    try:
        import xdg.BaseDirectory
        for directory in xdg.BaseDirectory.xdg_config_dirs:
            candidate = os.path.join(directory, config_fname)
            candidates.append(candidate)
            if os.path.exists(candidate):
                return candidate
    except ImportError:
        pass
    candidate = os.path.join(os.environ['HOME'], config_fname)
    if os.path.exists(candidate):
        return candidate
    candidates.append(candidate)
    raise Exception("No config file. Places examined: {}".format(
        ', '.join(candidates)
    ))


def context(section_name='main_backup'):
    """Read data, clean it up a bit
    """

    config = configparser.ConfigParser()
    config_fname = _config_file()
    config.read(config_fname)
    if section_name not in config:
        raise Exception("Need a '{}' section in {}".format(
            section_name, config_fname
        ))
    host = config[section_name]['host']
    src_dir = config[section_name]['src_dir']
    dst_dir = config[section_name]['dst_dir']
    logbase = config[section_name]['logbase']

    # if path does not end with /, trouble ahead with rsync.
    src_dir, dst_dir = (
        path if path.endswith('/') else path + '/'
        for path in (src_dir, dst_dir)
    )

    now = datetime.datetime.now()
    nowdir = os.path.join(
        '%i' % now.year,
        '%i' % now.month,
        '%i' % now.day,
        '%i_%i_%i.%i' % (now.hour, now.minute, now.second, now.microsecond)
    )

    os.makedirs(os.path.join(logbase, nowdir))
    log_fnames = (
        os.path.join(logbase, nowdir, fname)
        for fname in ('rsync_out', 'rsync_err', 'rsync_ret')
    )
    log_fds = (
        open(fname, 'w')
        for fname in log_fnames
    )

    ctx_args = (
        host,
        src_dir,
        dst_dir,
        os.path.join(
            logbase, nowdir, '{}.log'.format(
                os.path.basename(sys.argv[0])
            )
        )
        ) + tuple(log_fds)
    print(ctx_args)
    return Context(*ctx_args)


def setup_log(context):
    """Setup the logs for this script
    """
    logging.basicConfig(filename=context.logfile, level=logging.DEBUG)
    logger = logging.getLogger('main')
    # log to stdout
    logger.addHandler(StreamHandler(sys.stdout))
    return logger

if __name__ == '__main__':
    context = context()

    logger = setup_log(context)

    try:
        backup(context, logger)
    except BaseException as err:
        logger.exception("An error or interruption occured")
