
import tables as tb
import numpy as np
import time
from os.path import abspath, normpath, split as path_split, splitext, exists
import os
from distutils.version import LooseVersion
from collections import defaultdict
import operator
import itertools
import inspect
from functools import partial
try:
    from kivy.garden.collider import Collide2DPoly
except ImportError:
    Collide2DPoly = None
from kivy.compat import PY2
from kivy.event import EventDispatcher
import glitter

__DATA_SWITCH_VERSION__ = '3.0'

func_store = []


def create_if_not_exists(filename):
    if PY2:
        fd = os.open(filename, os.O_CREAT|os.O_EXCL)
        try:
            with os.fdopen(fd, 'w') as f:
                pass
        except:
            try:
                os.close(fd)
            except:
                pass
    else:
        with open(filename, 'x') as f:
            pass


def copy_tb_file(src, dest, overwrite=False):
    src = normpath(abspath(src))
    dest = normpath(abspath(dest))
    was_open = src in tb.file._open_files

    src_tb = tb.open_file(src)
    if not overwrite:
        create_if_not_exists(dest)
    src_tb.copy_file(dest, overwrite=True)
    if not was_open:
        src_tb.close()


class DataLogger(EventDispatcher):

    filename = ''
    tb_file = None
    needs_close = True

    data_h5 = None
    pts_h5 = None
    t_h5 = None
    xyt_h5 = None
    xy_h5 = None
    video_info_h5 = None

    _data_dict = None
    _chans_metadata_dict = None
    _file_metadata = None

    pts_list_complete = False
    unsaved_changes = False

    chan_map = {}

    current_file = None
    '''When exporting we need to access the current file, so this should be set
    to the one being analyzed.
    '''

    def __init__(self, filename=None, mode='r', **kwargs):
        super(DataLogger, self).__init__(**kwargs)
        if filename is not None:
            self.open_file(filename, mode)

    @property
    def chan_count(self):
        return self.tb_file.root._v_attrs.chan_count

    @chan_count.setter
    def chan_count(self, value):
        self.tb_file.root._v_attrs.chan_count = value

    @property
    def file_metadata(self):
        root = self.tb_file.root
        output = {}
        output['_version'] = root._v_attrs.Glitter_version
        output['_filename'] = root.video_info._v_attrs.file_name
        output['_filepath'] = root.video_info._v_attrs.file_path
        output['_video_params'] = root.video_info._v_attrs.video_params
        output['_username'] = root._v_attrs.username
        output['_video_id'] = root._v_attrs.video_id
        output['_user_comment'] = root._v_attrs.user_comment
        output['_creation_time'] = root._v_attrs.creation_time
        output['_ID'] = root._v_attrs.logID
        output['_seen_all_frames'] = root.video_info._v_attrs.seen_all_frames
        output['_chan_count'] = root._v_attrs.chan_count
        return output

    @property
    def channels_metadata(self):
        if self._chans_metadata_dict is not None:
            return self._chans_metadata_dict

        self._chans_metadata_dict = res = {}
        for group, group_type in ((self.t_h5, 't'), (self.xyt_h5, 'xyt'),
                      (self.xy_h5, 'xy')):
            for chan in group._f_iter_nodes():
                res[chan._v_name] = {
                    'config': chan._v_attrs['config'], '_name': chan._v_name,
                    'name': chan._v_attrs['name'],
                    'chan_type': group_type}
        return res

    @property
    def channels_data(self):
        '''Only valid while file is open.
        '''
        if self._data_dict is not None:
            return self._data_dict

        self._data_dict = data = {}
        data['pts'] = self.data_h5._f_list_nodes()

        for group in (self.t_h5, self.xyt_h5, self.xy_h5):
            for chan in group._f_iter_nodes():
                data[chan._v_name] = chan._f_list_nodes()
        return data

    @property
    def copy_channels_data(self):
        data = dict(self.channels_data)
        for k, v in data.items():
            data[k] = [np.array(arr) for arr in v]
        return data

    @property
    def timestamps(self):
        return self.pts_h5._f_list_nodes()

    @property
    def copy_timestamps(self):
        return [np.array(d) for d in self.pts_h5._f_list_nodes()]

    @property
    def unique_chan_names(self):
        '''Keys are the pretty name, if it's unique, mapping to the true
        name_n type name.
        '''
        name_count = defaultdict(int)
        names = {d['_name']: d['name'] for d in self.chans_metadata_dict}
        for name in names.values():
            name_count[name] += 1

        res = {}
        for real_name, pretty_name in names.items():
            if name_count[pretty_name] == 1:
                res[pretty_name] = real_name
            else:
                res[real_name] = real_name
        return res

    @property
    def pretty_channel_names(self):
        return {v: k for k, v in self.unique_chan_names.items()}

    def reload_data(self):
        '''Called to invalidate links and cached data upon a reload.
        '''
        self._data_dict = None
        self._chans_metadata_dict = None

    def open_file(self, filename, mode='r'):
        '''File must exist and be fully initialized.
        '''
        self.close_file()
        self.filename = filename = normpath(abspath(filename))
        self.needs_close = filename not in tb.file._open_files
        self.tb_file = tb_file = tb.open_file(filename, mode=mode)
        if LooseVersion(str(tb_file.root._v_attrs.Glitter_version)) < LooseVersion('3'):
            raise Exception('Need to import legacy file.')
        self.data_h5 = raw_data = tb_file.root.raw_data
        self.xy_h5 = raw_data.xy
        self.xyt_h5 = raw_data.xyt
        self.t_h5 = raw_data.t
        self.pts_h5 = raw_data.pts
        self.video_info_h5 = tb_file.root.video_info
        self.pts_list_complete = tb_file.root.video_info._v_attrs.seen_all_frames
        self.chan_map = mapping = {}
        for group in (self.t_h5, self.xyt_h5, self.xy_h5):
            for chan in group._f_iter_nodes():
                mapping[chan._v_name] = chan

    def close_file(self, force=False):
        '''Force false asssums a reverse close ordering compared to opening.
        '''
        if self.unsaved_changes:
            raise Exception('Unsaved changes')
        self.video_info_h5 = self.pts_h5 = self.t_h5 = self.xyt_h5 = \
            self.xy_h5 = self.data_h5 = None
        self.filename = ''
        if self.tb_file is not None and (self.needs_close or force):
            self.tb_file.close()
        self.tb_file = None
        self.reload_data()

    @staticmethod
    def create_file(
            filename, overwrite=False, video_width=0, video_height=0,
            video_name=''):
        '''Will overwrite file.
        '''
        filename = normpath(abspath(filename))
        if not overwrite:
            create_if_not_exists(filename)
        head, tail = path_split(filename)

        log = tb.open_file(filename, 'w')
        log.root._v_attrs.Glitter_version = glitter.__version__
        log.root._v_attrs.Glitter_description = glitter.__description__
        log.root._v_attrs.username = ''
        log.root._v_attrs.user_comment = ''
        log.root._v_attrs.video_id = ''
        log.root._v_attrs.chan_count = 0
        log.root._v_attrs.creation_time = time.strftime("%A, %B %d, %Y %I:%M:%S %p")
        log.root._v_attrs.logID = video_name
        raw_data = log.create_group(log.root, 'raw_data', 'The raw scores and time data.')
        video_group = log.create_group(log.root, 'video_info', 'Information about the video file.')
        video_group._v_attrs.file_path = head
        video_group._v_attrs.file_name = tail
        video_group._v_attrs.video_params = {'width': video_width, 'height': video_height}
        video_group._v_attrs.seen_all_frames = False

        log.create_group(raw_data, 'pts', 'lists of pts.')
        #log.create_earray(raw_data.pts, 'pts_0', tb.FloatAtom(), (0,), 'pts')
        log.create_group(raw_data, 't', 'lists of t based data.')
        log.create_group(raw_data, 'xyt', 'lists of xyt based data.')
        log.create_group(raw_data, 'xy', 'lists of xy zones.')
        log.close()

        return filename

    def save_template(self, filename, overwrite=False):
        filename = normpath(abspath(filename))
        self.copy_file(filename, overwrite)
        template_file = tb.open_file(filename, 'a')
        raw_group = template_file.root.raw_data

        for row in raw_group.pts._f_list_nodes():
            template_file.remove_node(row, recursive=True)

        for group_str in ('t', 'xy', 'xyt'):
            group = getattr(raw_group, group_str)
            for chan in group._f_iter_nodes():
                for row in chan._f_list_nodes():
                    template_file.remove_node(row, recursive=True)
        template_file.close()

    def copy_file(self, filename, overwrite=False):
        filename = normpath(abspath(filename))
        if not overwrite:
            create_if_not_exists(filename)
        self.tb_file.copy_file(filename, overwrite=True)

    @staticmethod
    def upgrade_legacy_file(src, dest, overwrite=False):
        '''Imports a legacy file.
        '''
        src = normpath(abspath(src))
        needs_close = src not in tb.file._open_files
        tb_src = tb.open_file(src)

        dest = normpath(abspath(dest))
        if not overwrite:
            create_if_not_exists(dest)

        if LooseVersion(str(tb_src.root._v_attrs.Glitter_version)) >= LooseVersion('3'):
            if needs_close:
                tb_src.close()
            raise Exception('{} was not a legacy file.')
        DataLogger.create_file(dest, overwrite=True)
        tb_dest = tb.open_file(dest, 'a')

        tb_dest.root._v_attrs.Glitter_version = glitter.__version__
        tb_dest.root._v_attrs.Glitter_description = glitter.__description__
        tb_dest.root._v_attrs.username = tb_src.root._v_attrs.username
        tb_dest.root._v_attrs.user_comment = tb_src.root._v_attrs.user_comment
        tb_dest.root._v_attrs.video_id = tb_src.root._v_attrs.video_id
        tb_dest.root._v_attrs.creation_time = tb_src.root._v_attrs.creation_time
        tb_dest.root._v_attrs.logID = tb_src.root._v_attrs.logID

        video_group = tb_dest.root.video_info
        video_group._v_attrs.file_path = tb_src.root.video_info._v_attrs.file_path
        video_group._v_attrs.file_name = tb_src.root.video_info._v_attrs.file_name
        video_group._v_attrs.video_params['width'] = tb_src.root.video_info._v_attrs.video_params['width']
        video_group._v_attrs.video_params['height'] = tb_src.root.video_info._v_attrs.video_params['height']
        video_group._v_attrs.video_params = dict(video_group._v_attrs.video_params)
        video_group._v_attrs.seen_all_frames = tb_src.root.video_info._v_attrs.seen_all_frames

        count = 0
        raw_data = tb_dest.root.raw_data
        for row in tb_src.root.raw_data.pts._f_iter_nodes():
            if not row.nrows:
                continue
            tb_src.copy_node(row, raw_data.pts)

        for group in tb_src.root.raw_data._f_iter_nodes():
            if group._v_name == 'pts':
                continue
            attrs = group._v_attrs
            chan_type = attrs['score_type']
            chan = tb_dest.create_group(getattr(raw_data, chan_type), group._v_name, attrs['name'])
            chan._v_attrs['name'] = group._v_attrs['name']
            chan._v_attrs['config'] = {k: group._v_attrs[k] for k in DataLogger.get_default_settings(chan_type)['config'].keys()}

            count = max(count, int(group._v_name.rpartition('_')[2]) + 1)
            for row in group._f_iter_nodes():
                if not row.nrows:
                    continue
                tb_src.copy_node(row, chan)

        tb_dest.root._v_attrs.chan_count = count

        if needs_close:
            tb_src.close()
        tb_dest.close()

    def import_hdf5_file(self, filename):
        if not self.pts_list_complete:
            raise Exception('Cannot import while there are unseen frames.')
        filename = normpath(abspath(filename))
        src = DataLogger(filename=filename, mode='a')
        tb_src, tb_dest = src.tb_file, self.tb_file

        if LooseVersion(str(tb_src.root._v_attrs.Glitter_version)) < LooseVersion(__DATA_SWITCH_VERSION__):
            raise Exception('Need to import legacy file.')

        src_chans = src.chans_metadata_dict
        count = self.chan_count
        src_pts, dest_pts = src.pts_h5, self.pts_h5

        for chan in src_chans:
            node = getattr(getattr(tb_src.root.raw_data, chan['chan_type']), chan['_name'])
            newname = '{}_{}'.format(chan['name'], count)
            count += 1

            if chan['chan_type'] == 'xy':
                tb_src.copy_node(
                    node, self.xy_h5, newname=newname, recursive=True)
                new_node = getattr(self.xy_h5, newname)
                tb_src.copy_node_attrs(node, new_node)
            elif chan['chan_type'] == 'xyt':
                pass

        self.chan_count = count
        src.close_file()
        filenam = self.filename
        self.close_file()
        self.open_file(filename, 'a')
        self.unsaved_changes = True

    @staticmethod
    def get_default_settings(chan_type):
        if chan_type == 'xyt':
            config = {'color': [1,1,1,1], 'draw': False, 'plot': True}
        elif chan_type == 'xy':
            config = {'color': [1,1,1,1], 'draw': False}
        elif chan_type == 't':
            config = {
                'color': [1,1,1,1], 'draw': False, 'plot': True,
                'event_type': 'press', 'keycode': '', 'group': ''}
        return {'config': config, 'name': ''}

    @staticmethod
    def get_default_chan_val(chan_type):
        if chan_type == 'xyt':
            return (tb.IntAtom(shape=(2)), (-1, -1))
        elif chan_type == 'xy':
            return (tb.IntAtom(shape=(2)), (-1, -1))
        elif chan_type == 't':
            return (tb.BoolAtom(), False)

    def set_user_params(self, name=None, comment=None):
        if name is not None:
            self.tb_file.root._v_attrs.username = name
        if comment is not None:
            self.tb_file.root._v_attrs.user_comment = comment
        self.unsaved_changes = True

    def get_user_params(self):
        attrs = self.tb_file.root._v_attrs
        return attrs.username, attrs.user_comment

    def edit_channel_metadata(self, name, **kwargs):
        self.reload_data()
        chan = self.chan_map[name]
        self.unsaved_changes = True
        if chan._v_attrs['name'] != kwargs.get('name', chan._v_attrs['name']):
            chan._f_rename('{}_{}'.format(kwargs['name'], chan._v_name.rpartition('_')[2]))
            for row in chan._f_list_nodes():
                row._f_rename('{}_{}'.format(kwargs['name'], row._v_name.rpartition('_')[2]))

        for key, val in kwargs.items():
            chan._v_attrs[key] = val

    def add_channel(self, name, chan_type, **kwargs):
        assert chan_type in ('xy', 'xyt', 't')
        count = self.chan_count
        self.chan_count += 1
        self.unsaved_changes = True
        self.reload_data()
        tb_file = self.tb_file

        group = getattr(self.data_h5, chan_type)
        chan_name = '{}_{}'.format(name, count)
        self.chan_map[chan_name] = chan = self.tb_file.create_group(group, chan_name, name)

        atom, value = self.get_default_chan_val(chan_type)
        settings = self.get_default_settings(chan_type)
        settings.update(kwargs)

        for key, val in settings.items():
            chan._v_attrs[key] = val
        if chan_type == 'xy':
            tb_file.create_earray(chan, '{}_0'.format(name), atom, (0,), name)
            return
        for i, leaf in enumerate(self.pts_h5._v_leaves.values()):
            elem = tb_file.create_earray(chan, '{}_{}'.format(name, i), atom, (0,), name)
            elem.append([value] * leaf.nrows)

    def delete_channel(self, name):
        self.unsaved_changes = True
        self.reload_data()
        self.tb_file.remove_node(self.chan_map[name], recursive=True)
        del self.chan_map[name]

    def clear_channel(self, name):
        self.unsaved_changes = True
        chan = self.chan_map[name]
        chan_type = chan._v_parent._v_name

        if chan_type == 'xy':
            assert len(chan._v_leaves.values()) == 1
            chan._v_leaves.values()[0].truncate(0)
        else:
            _, value = self.get_default_chan_val(chan_type)
            for row_group in chan._v_leaves:
                for row in range(row_group.nrows):
                    row_group[row] = value


class DataFunction(object):

    func = None
    name = None
    description = None
    arg_names = None

    def __init__(self, func=None, name=None, desc=None, params=None):
        self.func = func
        self.name = name
        self.description = desc
        arg_names = self.arg_names = \
            inspect.getargspec(func)[0] if func is not None else ()


class FunctionParameter(object):

    name = None
    description = None
    lookup = False
    verify = None
    convert = None
    param_code = None
    opts = None
    default = None
    optional = None

    variable_registry = {'mapping': []}

    def __init__(
        self, name=None, desc=None, verify=None, convert=None,
        param_code=None, opts=None, default=None, optional=False):
        self.name = name
        self.description = desc
        self.verify = verify
        self.convert = convert
        self.param_code = param_code
        self.opts = opts
        self.default = default
        self.optional = optional


def list_channels_names(chan_types):
    f = DataLogger.current_file
    metadata = f.chans_metadata_dict
    names = f.pretty_channel_names

    items = []

    for name, chan_info in metadata.items():
        if chan_info['chan_type'] in chan_types:
            items.append(names[name])
    return items


def get_ts_of_data(channel, state, pos):
    f = DataLogger.current_file
    data_dict = f.channels_data
    pts = data_dict['pts']
    channel = data_dict[f.unique_chan_names[channel]]
    matched = [pts[i][j] for i, g in enumerate(channel)
               for j, r in enumerate(g) if r == state]
    if not len(matched):
        raise ValueError('Channel does not have data that is {}'.format(state))
    if len(matched) == 1 or pos == 'First':
        return matched[0]
    if pos == 'Last':
        return matched[-1]
    raise Exception('Channel has more than one data point {}'.format(state))

# f = DataFunction(
#     func=get_ts_of_data, name='Get timepoint of the start/end or only data '
#     'point with value "state"', params={
#         'channel': FunctionParameter(
#             opts=partial(list_channels_match, ['xyt', 't'])),
#         'state': FunctionParameter(opts=['Active', 'Inactive']),
#         'pos': FunctionParameter(opts=['First', 'Last', 'Only'])
#     }
# )
# func_store.append(f)
