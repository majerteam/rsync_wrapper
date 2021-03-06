Run rsync backup and log all data.
==================================

Install
========

Currently has to be ran from its place. This is a self contained script as can be.

Requisite
----------

Python >= 3.3

Config file
===========

The config file is mandatory.

Places for config file
-----------------------

File must be named run_backup.rc and can exist in any xdg config dirs,
or in the user's home.

If not found, the exe will tell you where it looked for it.

Example config file
-----------------------

.. code-block:: ini

        [main_backup]
        host=192.168.12.26
        src_dir=/dir/to/sync/
        dst_dir=/mirror/of/dir
        logbase=/place/where/i/log
        mailto=user@example.com
        timeout_secs=14000

        [mail]
        smtp=smtp.example.com
        mailfrom=robots@example.com


Timeout
========

An *optional* timeout can be specified in seconds. After this time, rsync will receive SIGINT.

Logs
======

Logs are stored in the directory you specify, under a directory hierarchy of YYYY/MM/DD/hh_mm_ss.microseconds

Mails
=======

Sending mail or not
----------------------

If there is no mailto in 'main_backup', no mail will be sent.

Mail subject
-------------

the title of the mail looks like::

    [time expired] backup of 192.168.12.26:/dir/to/sync/ on /mirror/of/dir/

Possible statuses:

* success
* failure (non 0 code for rsync)
* time expired

Plans
======

* Simple packaging
* Support command line options.
* Support several backups at the same time.
