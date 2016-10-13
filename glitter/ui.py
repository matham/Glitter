from os.path import split as path_split, splitext, abspath, normpath, join
from os.path import isfile, isdir
import tempfile
from glitter.logger import DataLogger, copy_tb_file, create_if_not_exists
from glitter.video import VideoPlayer
from glitter.utils import to_bool
from glitter import glitter_config

from kivy.event import EventDispatcher
from kivy.properties import ConfigParserProperty, ObjectProperty


class DataController(EventDispatcher):

    data_name = ''
    auto_save_name = ''
    data_logger = None

    _do_autosave = False
    '''Whether the data file will be autosaved. If no data file is opened by
    the user, an internal file still be opened. Autosave refers to an
    additional file.
    '''

    video_filename = ''
    player = None

    autosave_duration = ConfigParserProperty(
        5., 'Data', 'autosave_duration', glitter_config, val_type=float,
        verify=lambda x: x >= 0., errorvalue=5.)

    data_path = ConfigParserProperty(
        '', 'Data', 'data_path', glitter_config, val_type=str)

    auto_create_data = ConfigParserProperty(
        True, 'Data', 'auto_create_data', glitter_config, val_type=to_bool,
        errorvalue=True)

    def get_tempfile(self, data_path, tail):
        temp_file = tempfile.NamedTemporaryFile(
            dir=data_path, prefix=tail + '_', suffix='.autosave', delete=False)
        temp_name = temp_file.name
        temp_file.close()
        return temp_name

    def open_video(self, filename):
        self.close_video()
        filename = abspath(normpath(filename))
        self.player = player = VideoPlayer(filename)
        self.video_filename = filename

        self._do_autosave = bool(self.autosave_duration)
        head, tail = path_split(filename)
        tail = splitext(tail)[0]
        data_path = self.data_path if self.data_path and isdir(self.data_path) else head

        fname = join(data_path, hf_name)
        if isfile(fname):
            self.load_data_file(fname)
        elif self.auto_create_data:
            self.create_data_file(fname)
        else:
            self.create_internal_file(data_path, tail)

    def close_video(self):
        self.close_data_file()
        if self.player is not None:
            self.player.close()
            self.player = None
        self.video_filename = ''

    def create_data_file(self, filename, overwrite=False):
        self.close_data_file()
        if not overwrite:
            create_if_not_exists(filename)

        head, tail = path_split(filename)
        tail = splitext(tail)[0]

        log = DataLogger()
        log.create_file(
            filename, overwrite=True, video_width=0, video_height=0,
            video_name=tail)
        log.close_file()
        return self.load_data_file(filename)

    def create_internal_file(self, data_path, tail):
        self.close_data_file()

        log = DataLogger()
        tfile = self.get_tempfile(data_path, tail)
        log.create_file(tfile, overwrite=True, video_width=0, video_height=0, video_name=tail)
        self.auto_save_name = tfile
        self.data_name = ''
        self.data_logger = log

    def load_data_file(self, filename):
        self.close_data_file()

        log = DataLogger()
        tfile = ''
        head, tail = path_split(filename)
        tail = splitext(tail)[0]

        if self._do_autosave:
            tfile = self.get_tempfile(head, tail)
            copy_tb_file(filename, tfile, overwrite=True)
            log.open_file(tfile)
        else:
            log.open_file(filename)
        self.auto_save_name = tfile
        self.data_name = filename
        self.data_logger = log

    def close_data_file(self):
        data_logger = self.data_logger
        if data_logger is not None:
            if data_logger.unsaved_changes:
                pass
            data_logger.close_file()
            self.data_logger = None
        self.data_name = self.auto_save_name = ''

