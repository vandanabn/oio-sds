# Copyright (C) 2019 OpenIO SAS, as part of OpenIO SDS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from itertools import chain
from urllib import quote
from urlparse import urlparse

from cliff import lister

from oio.common import exceptions
from oio.common.fullpath import encode_fullpath
from oio.common.utils import cid_from_name
from oio.cli.admin.common import ContainerCommandMixin, ObjectCommandMixin


DUMMY_SERVICE = {'addr': None, 'score': 0, 'tags': {}}


class ItemLocateCommand(lister.Lister):
    """
    A command to display which service is in charge of hosting an item.
    """

    columns = ('Type', 'Item', 'Service Id', 'Addr', 'Location', 'Status')
    reqid_prefix = 'ACLI-LOC-'

    def __init__(self, *args, **kwargs):
        super(ItemLocateCommand, self).__init__(*args, **kwargs)
        self._srv_cache = dict()

    # Accessors #######################################################

    @property
    def account(self):
        """Get an instance of AccountClient."""
        return self.storage.account

    @property
    def cs(self):
        """Get an instance of ConscienceClient."""
        return self.account.cs

    @property
    def digits(self):
        """Get the number of digits used to group CID prefixes."""
        return self.app.client_manager.meta1_digits

    @property
    def dir(self):
        """Get an instance of DirectoryClient."""
        return self.storage.directory

    @property
    def logger(self):
        return self.app.client_manager.logger

    @property
    def storage(self):
        """Get an instance of ObjectStorageApi."""
        return self.app.client_manager.storage

    # Cliff ###########################################################

    def get_parser(self, prog_name):
        parser = super(ItemLocateCommand, self).get_parser(prog_name)
        return parser

    # Utility #########################################################

    def all_services(self, srv_type, **kwargs):
        """
        Get a dictionary of (cached) services of the specified type.
        """
        if srv_type not in self._srv_cache:
            services = self.cs.all_services(srv_type, **kwargs)
            self._srv_cache[srv_type] = {s['id']: s for s in services}
        return self._srv_cache[srv_type]

    def cid_to_m1(self, cid):
        """
        Get the name of the meta1 database where the reference information
        will be stored. Output will always have 4 hexdigits.
        """
        return cid[:self.digits].ljust(4, '0')[:4]

    def m2_item(self, acct, ct, cid):
        return '%s/%s (%s)' % (quote(acct), quote(ct), cid)

    def locate_accounts(self, accounts):
        reqid = self.app.request_id(self.reqid_prefix)
        all_acct = self.all_services('account', reqid=reqid)
        for acct in accounts:
            try:
                # TODO(FVE): do something with the result?
                self.account.account_show(acct, reqid=reqid)
            except Exception as err:
                yield ('account', acct, 'n/a', 'n/a', 'n/a', str(err))
                continue
            finally:
                reqid = self.app.request_id(self.reqid_prefix)
            for srv in all_acct.values():
                status = 'up=%s, score=%s' % (srv['tags'].get('tag.up', False),
                                              srv['score'])
                yield ('account', acct, srv['id'], srv['addr'],
                       srv['tags'].get('tag.loc', 'n/a'),
                       status)

    def locate_m0(self, cid='', known_m0=None, error=None):
        """
        Locate the meta0 services responsible for `cid`.

        :param known_m0: if provided, filter the list of all meta0 services,
            and keep only these ones.
        """
        reqid = self.app.request_id(self.reqid_prefix)
        all_m0 = self.all_services('meta0', reqid=reqid)
        if known_m0:
            m0_srv = [all_m0.get(s['host'], DUMMY_SERVICE) for s in known_m0]
        else:
            m0_srv = all_m0.values()
        cid = self.cid_to_m1(cid)
        for m0 in m0_srv:
            status = 'up=%s, score=%s' % (m0['tags'].get('tag.up', False),
                                          m0['score'])
            yield ('meta0',
                   '%s (%s.meta0)' % (cid, self.app.options.ns),
                   m0['id'],
                   m0['addr'],
                   m0['tags'].get('tag.loc', 'n/a'),
                   str(error) if error else status)

    def format_m1(self, cid, m1_srv):
        reqid = self.app.request_id(self.reqid_prefix)
        all_m1 = self.all_services('meta1', reqid=reqid)
        for m1 in m1_srv:
            m1_descr = all_m1.get(m1['host'], DUMMY_SERVICE)
            status = 'up=%s, score=%s' % (
                m1_descr['tags'].get('tag.up', False), m1_descr['score'])
            yield ('meta1',
                   '%s (%s.meta1)' % (cid, self.cid_to_m1(cid)),
                   m1['host'],
                   m1_descr['addr'],
                   m1_descr['tags'].get('tag.loc', 'n/a'),
                   status)

    def format_m2(self, acct, ct, m2_srv):
        cid = cid_from_name(acct, ct)
        m2_item = self.m2_item(acct, ct, cid)
        reqid = self.app.request_id(self.reqid_prefix)
        all_m2 = self.all_services('meta2', reqid=reqid)
        for m2 in m2_srv:
            m2_descr = all_m2.get(m2['host'], DUMMY_SERVICE)
            status = 'up=%s, score=%s' % (
                m2_descr['tags'].get('tag.up', False), m2_descr['score'])
            yield ('meta2', m2_item,
                   m2['host'], m2_descr['addr'],
                   m2_descr['tags'].get('tag.loc', 'n/a'),
                   status)

    def format_chunks(self, chunks, obj=None):
        reqid = self.app.request_id(self.reqid_prefix)
        all_rawx = self.all_services('rawx', reqid=reqid)
        for chunk in chunks:
            host = urlparse(chunk['url']).netloc
            descr = all_rawx.get(host, DUMMY_SERVICE)
            status = 'up=%s, score=%s' % (
                descr['tags'].get('tag.up', False), descr['score'])
            error = chunk.get('error')
            pos = chunk.get('pos') or chunk.get('chunk_pos')
            fp = chunk.get('full_path', obj)
            yield ('rawx',
                   '%s pos=%s (%s)' % (fp, pos, chunk['url']),
                   host,
                   descr['addr'],
                   descr['tags'].get('tag.loc', 'n/a'),
                   str(error) if error else status)

    def locate_containers(self, containers, is_cid=False):
        reqid = self.app.request_id(self.reqid_prefix)
        # FIXME(FVE): manage --cid here
        for ct in containers:
            try:
                if is_cid:
                    cid = ct
                    # Unfortunately, self.dir.list() does not
                    # resolve container ID, we must do another request.
                    acct, ct = self.app.client_manager.storage.resolve_cid(cid)
                else:
                    acct = self.app.options.account
                    cid = cid_from_name(acct, ct)
                dir_data = self.dir.list(cid=cid, reqid=reqid)
            except (exceptions.NotFound, exceptions.ServiceBusy) as err:
                m0_err = err if 'meta0' in str(err) else None
                for m0 in self.locate_m0(cid, error=m0_err):
                    yield m0
                yield ('meta1',
                       '%s (%s.meta1)' % (cid, self.cid_to_m1(cid)),
                       'n/a',
                       'n/a',
                       'n/a',
                       str(err))
                continue
            finally:
                reqid = self.app.request_id(self.reqid_prefix)

            m0_srv = [x for x in dir_data['dir'] if x['type'] == 'meta0']
            for m0 in self.locate_m0(cid, m0_srv):
                yield m0

            m1_srv = [x for x in dir_data['dir'] if x['type'] == 'meta1']
            for m1 in self.format_m1(cid, m1_srv):
                yield m1

            m2_srv = [x for x in dir_data['srv'] if x['type'] == 'meta2']
            for m2 in self.format_m2(acct, ct, m2_srv):
                yield m2
            if not m2_srv:
                yield ('meta2',
                       self.m2_item(acct, ct, cid),
                       None, None, None,
                       'Reference exists but no meta2 service is linked')

    def locate_objects(self, objects):
        reqid = self.app.request_id(self.reqid_prefix)
        for ct, obj, vers in objects:
            obj_item = '/'.join(quote(x) for x in (
                self.app.options.account, ct, obj, str(vers)))
            try:
                obj_md, chunks = self.storage.object_locate(
                    self.app.options.account, ct, obj, version=vers,
                    chunk_info=True, reqid=reqid)
                obj_item = encode_fullpath(self.app.options.account, ct, obj,
                                           obj_md['version'], obj_md['id'])
            except exceptions.NoSuchContainer as err:
                self.logger.warn('Failed to locate object %s: %s',
                                 obj_item, err)
                # Already reported by upper level
                continue
            except exceptions.NoSuchObject as err:
                yield ('rawx', obj_item, None, None, None, str(err))
                continue
            except Exception as err:
                self.logger.warn('Failed to locate object %s: %s',
                                 obj_item, err)
                continue
            finally:
                reqid = self.app.request_id(self.reqid_prefix)
            for chunk in self.format_chunks(chunks, obj_item):
                yield chunk

    def locate_chunks(self, chunks):
        reqid = self.app.request_id(self.reqid_prefix)
        for chunk in chunks:
            chunk_obj = {'url': chunk}
            try:
                xattr_meta = self.storage.blob_client.chunk_head(
                    chunk, reqid=reqid)
                chunk_obj.update(xattr_meta)
            except Exception as err:
                chunk_obj['error'] = err
            finally:
                reqid = self.app.request_id(self.reqid_prefix)
            for line in self.format_chunks((chunk_obj, )):
                yield line


class AccountLocate(ItemLocateCommand):
    """
    Get location of the account service(s) hosting the specified account.
    """

    reqid_prefix = 'ACLI-AL-'

    def get_parser(self, prog_name):
        parser = super(AccountLocate, self).get_parser(prog_name)
        parser.add_argument(
            'accounts',
            nargs='*',
            metavar='<account_name>',
            help='Name of the account to check.'
        )
        return parser

    def take_action(self, parsed_args):
        super(AccountLocate, self).take_action(parsed_args)
        if not parsed_args.accounts:
            parsed_args.accounts = [self.app.options.account]
        return self.columns, self.locate_accounts(parsed_args.accounts)


class ContainerLocate(ContainerCommandMixin, ItemLocateCommand):
    """
    Get location of the services involved
    in hosting the specified container(s).
    """
    reqid_prefix = 'ACLI-CL-'

    def get_parser(self, prog_name):
        parser = super(ContainerLocate, self).get_parser(prog_name)
        self.patch_parser(parser)
        return parser

    def take_action(self, parsed_args):
        super(ContainerLocate, self).take_action(parsed_args)
        # FIXME(FVE): inconsistent behavior: we locate the account
        # found in environment even though the specified container IDs
        # can be resolved as other accounts.
        # The locate_containers() method should be in charge of
        # calling locate_accounts() after container ID resolution.
        return self.columns, chain(
            self.locate_accounts([self.app.options.account]),
            self.locate_containers(parsed_args.containers,
                                   is_cid=parsed_args.is_cid))


class ObjectLocate(ObjectCommandMixin, ItemLocateCommand):
    """
    Get location of the services involved
    in hosting the specified object(s).
    """
    reqid_prefix = 'ACLI-OL-'

    def get_parser(self, prog_name):
        parser = super(ObjectLocate, self).get_parser(prog_name)
        self.patch_parser(parser)
        return parser

    def resolve_objects(self, parsed_args):
        containers = set()
        objects = list()
        if parsed_args.auto:
            autocontainer = self.app.client_manager.flatns_manager
            for obj in parsed_args.objects:
                ct = autocontainer(obj)
                containers.add(ct)
                objects.append((ct, obj, parsed_args.object_version))
        else:
            if parsed_args.is_cid:
                account, container = \
                    self.app.client_manager.storage.resolve_cid(
                        parsed_args.container)
            else:
                account = self.app.options.account
                container = parsed_args.container
            containers.add(container)
            for obj in parsed_args.objects:
                objects.append(
                    (container, obj, parsed_args.object_version))
        return account, containers, objects

    def take_action(self, parsed_args):
        super(ObjectLocate, self).take_action(parsed_args)
        account, containers, objects = self.resolve_objects(parsed_args)
        return self.columns, chain(
            self.locate_accounts([account]),
            self.locate_containers(containers),
            self.locate_objects(objects))


class ChunkLocate(ItemLocateCommand):
    """
    Get location of the services involved
    in hosting the specified chunk(s).
    """
    reqid_prefix = 'ACLI-CKL-'

    def get_parser(self, prog_name):
        parser = super(ChunkLocate, self).get_parser(prog_name)
        parser.add_argument(
            'chunks',
            metavar='<chunk_url>',
            nargs='+',
            help='URL to the chunk to check.'
        )
        return parser

    def take_action(self, parsed_args):
        super(ChunkLocate, self).take_action(parsed_args)
        return self.columns, chain(
            self.locate_chunks(parsed_args.chunks))
