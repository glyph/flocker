# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Testing utilities provided by ``flocker.volume``.
"""

import os
import uuid
import subprocess
from unittest import SkipTest

from characteristic import attributes

from twisted.python.filepath import FilePath
from twisted.internet.task import Clock
from twisted.internet import reactor

from ..common import ProcessNode
from ._ipc import RemoteVolumeManager

from .filesystems.zfs import StoragePool
from .service import VolumeService
from .filesystems.memory import FilesystemStoragePool


def create_volume_service(test):
    """
    Create a new ``VolumeService`` suitable for use in unit tests.

    :param TestCase test: A unit test which will shut down the service
        when done.

    :return: The ``VolumeService`` created.
    """
    service = VolumeService(FilePath(test.mktemp()),
                            FilesystemStoragePool(FilePath(test.mktemp())),
                            reactor=Clock())
    service.startService()
    test.addCleanup(service.stopService)
    return service


def create_zfs_pool(test_case):
    """Create a new ZFS pool, then delete it after the test is over.

    :param test_case: A ``unittest.TestCase``.

    :return: The pool's name as ``bytes``.
    """
    if os.getuid() != 0:
        raise SkipTest("Functional tests must run as root.")

    pool_name = b"testpool_%s" % (uuid.uuid4(),)
    pool_path = FilePath(test_case.mktemp())
    mount_path = FilePath(test_case.mktemp())
    with pool_path.open("wb") as f:
        f.truncate(100 * 1024 * 1024)
    test_case.addCleanup(pool_path.remove)
    subprocess.check_call([b"zpool", b"create", b"-m", mount_path.path,
                           pool_name, pool_path.path])
    test_case.addCleanup(subprocess.check_call,
                         [b"zpool", b"destroy", pool_name])
    return pool_name


class MutatingProcessNode(ProcessNode):
    """Mutate the command being run in order to make tests work.

    Come up with something better in
    https://github.com/ClusterHQ/flocker/issues/125
    """
    def __init__(self, to_service):
        """
        :param to_service: The VolumeService to which a push is being done.
        """
        self.to_service = to_service
        ProcessNode.__init__(self, initial_command_arguments=[])

    def _mutate(self, remote_command):
        """
        Add the pool and mountpoint arguments, which aren't necessary in real
        code.

        :param remote_command: Original command arguments.

        :return: Modified command arguments.
        """
        return remote_command[:1] + [
            b"--pool", self.to_service._pool._name,
            b"--mountpoint", self.to_service._pool._mount_root.path
        ] + remote_command[1:]

    def run(self, remote_command):
        return ProcessNode.run(self, self._mutate(remote_command))

    def get_output(self, remote_command):
        return ProcessNode.get_output(self, self._mutate(remote_command))


@attributes(["from_service", "to_service", "remote"])
class ServicePair(object):
    """
    A configuration for testing ``IRemoteVolumeManager``.

    :param VolumeService from_service: The origin service.
    :param VolumeService to_service: The destination service.
    :param IRemoteVolumeManager remote: Talks to ``to_service``.
    """


def create_realistic_servicepair(test):
    """
    Create a ``ServicePair`` that uses ZFS for testing
    ``RemoteVolumeManager``.

    :param TestCase test: A unit test.

    :return: A new ``ServicePair``.
    """
    from_pool = StoragePool(reactor, create_zfs_pool(test),
                            FilePath(test.mktemp()))
    from_service = VolumeService(FilePath(test.mktemp()),
                                 from_pool, reactor=Clock())
    from_service.startService()
    test.addCleanup(from_service.stopService)

    to_pool = StoragePool(reactor, create_zfs_pool(test),
                          FilePath(test.mktemp()))
    to_config = FilePath(test.mktemp())
    to_service = VolumeService(to_config, to_pool, reactor=Clock())
    to_service.startService()
    test.addCleanup(to_service.stopService)

    remote = RemoteVolumeManager(MutatingProcessNode(to_service),
                                 to_config)
    return ServicePair(from_service=from_service, to_service=to_service,
                       remote=remote)
