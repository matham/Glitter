from ffpyplayer import FFPyPlayer, set_log_callback, loglevels
import os
import logging
import sys
import itertools
import tables as tb
import tempfile
import time
try:
    import glitter
except:
    import __init__ as glitter
import operator
import bisect
import csv
import weakref
# use the most recent exporter present on the system
from misc import PyTrackException
if getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(sys.executable))
try:
    from exporter import DataList
except ImportError:
    pass    # there's a default exporter with the exe
if getattr(sys, 'frozen', False):
    del sys.path[0]

# TODO: when importing a data file, sparse data should be stretched to fill the whole time series.

def ffplayer_callback(*largs):
    pass

logger_func = {'quiet': logging.critical, 'panic': logging.critical,
               'fatal': logging.critical, 'error': logging.error,
               'warning': logging.warning, 'info': logging.info,
               'verbose': logging.debug, 'debug': logging.debug}

def log_callback(message, level):
    message = message.strip()
    if message and loglevels[level] <= loglevels['info']:
        logger_func[level]('ffpyplayer:%s' % message)

# a temp file is created when the object is created and is deleted when a new tempfile
# is opened (loading a new log) or when the object is closed. A autosave and permenant
#log file is open when user loads log, and closed when user closes log.
class TrackLog(object):
    media = None
    filename = None
    filetail = ''
    filehead = ''
    status_func = None
    autosave_writer = None
    edit_pts_break_func = None

    log= ''
    log_auto = ''
    log_temp = ''
    log_auto_dur = 0.0
    unsaved_changes = False
    raw_group = None
    pts_group = None
    score_groups = None
    video_info_group = None


    duration= None
    frame_size = None

    fwd_points = 2.0
    back_points = 2.0


    data= None  # a list of pts followed by cols
    # dict with keys being pts, and values a list l: l[0], l[1] is the list and index in list from data for this pts
    pts_list = None
    pts_list_complete = False
    jumped = False
    last_list = None
    update_notifier = None

    @staticmethod
    def import_data_file(filename):
        output = {}
        was_open = filename in [fname for fname in tb.file._open_files]
        datafile = tb.open_file(filename)
        output['_version'] = datafile.root._v_attrs.Glitter_version
        output['_filename'] = datafile.root.video_info._v_attrs.file_name
        output['_vid_info'] = datafile.root.video_info._v_attrs.video_params
        output['_username'] = datafile.root._v_attrs.username
        output['_video_id'] = datafile.root._v_attrs.video_id
        output['_user_comment'] = datafile.root._v_attrs.user_comment
        output['_ID'] = datafile.root._v_attrs.logID
        output['_complete'] = datafile.root.video_info._v_attrs.seen_all_frames
        raw_group = datafile.root.raw_data
        pts_group = datafile.root.raw_data.pts

        groups = [None,] * (raw_group._v_nchildren-1)
        channels = [None,] * (raw_group._v_nchildren)
        for group in raw_group._f_iter_nodes():
            if group._v_name != 'pts':
                groups[int(group._v_name.rpartition('_')[2])] = group
        n_pts = len(pts_group._f_list_nodes())
        data = [[None for j in range(len(groups)+1)] for i in range(n_pts)]
        for col in range(len(groups)):
            for row in groups[col]._f_iter_nodes():
                data[int(row._v_name.rpartition('_')[2])][col + 1] = row
        for row in pts_group._f_iter_nodes():
            data[int(row._v_name.rpartition('_')[2])][0] = row
        for i in range(len(groups)):
            name = groups[i]._v_name.rpartition('_')[0]
            channels[1+i] = DataList(output, groups[i]._v_attrs['score_type'],
                                     name, name)
            output[channels[1+i].name] = channels[1+i]
            output[groups[i]._v_name] = channels[1+i]
        channels[0] = DataList(output, 'pts', 'pts', 'pts')
        output['_pts'] = channels[0]
        for i in range(len(data)):
            channels[0].extend(data[i][0][:])
            channels[0].append(data[i][0][-1])
            for j in range(len(data[i])-1):
                if (not i) or channels[1+j].score_type != 'xy':
                    channels[1+j].extend(data[i][1+j][:])
                    if channels[1+j].score_type != 'xy':
                        channels[1+j].append(TrackLog.get_default_score_val(channels[1+j].score_type)[1])
        for channel in channels:
            channel.pts = range(len(channel))
        if not was_open:
            datafile.close()
        return output

    @staticmethod
    def get_default_settings(score_type):
        if score_type == 'xyt':
            return {'color':[1,1,1,1], 'name':'', 'draw':False, 'score_type':'xyt', 'plot':True}
        elif score_type == 'xy':
            return {'color':[1,1,1,1], 'name':'', 'draw':False, 'score_type':'xy'}
        elif score_type == 't':
            return {'color':[1,1,1,1], 'name':'', 'draw':False, 'score_type':'t',
                    'plot':True, 'event_type':'press', 'keycode':'', 'group':''}

    @staticmethod
    def get_default_score_val(score_type):
        if score_type == 'xyt':
            return (tb.IntAtom(shape=(2)), (-1, -1))
        elif score_type == 'xy':
            return (tb.IntAtom(shape=(2)), (-1, -1))
        elif score_type == 't':
            return (tb.BoolAtom(), False)

    def __init__(self, filename, headers, auto_time, status_func, autosave_writer,
                 update_notifier, edit_pts_break_func):
        logging.info('Opening video file %s' % filename)
        set_log_callback(log_callback)
        self.media= FFPyPlayer(filename, vid_sink=weakref.ref(ffplayer_callback),
                               loglevel='info', ff_opts={'an':1, 'sn':1, 'sync':'video'})
        start_t = time.clock()
        while time.clock() < start_t + 60 and not self.media.get_metadata()['duration']:
            time.sleep(0.1)
        if not self.media.get_metadata()['duration']:
            raise Exception('Waiting for video duration timed out.')
        self.duration = self.media.get_metadata()['duration']
        frame, val = self.media.get_frame()
        while (not frame) and val != 'eof' and val != 'pause':
            time.sleep(0.1)
            frame, val = self.media.get_frame()
        if not frame:
            raise Exception('Waiting for first video frame timed out.')
        self.frame_size = self.media.get_metadata()['src_vid_size']
        self.cached_frame = frame

        self.filename= filename
        self.filehead = os.path.split(os.path.splitext(os.path.normpath(filename))[0])
        self.filetail = self.filehead[1]
        self.filehead = self.filehead[0]
        self.log = ''      # the log file
        self.log_auto = ''      # the autosave log file
        self.log_auto_dur = auto_time
        self.status_func = status_func
        self.autosave_writer = autosave_writer
        self.unsaved_changes = False
        self.pts_list_complete = False
        self.update_notifier = update_notifier
        self.edit_pts_break_func = edit_pts_break_func

        temp_file = tempfile.NamedTemporaryFile(prefix=self.filetail+'_', delete=False)
        temp_name = temp_file.name
        temp_file.close()
        log = tb.open_file(temp_name, 'w')
        self.log_temp = log
        logging.info('Creating internal log file at: %s' % log)
        log.root._v_attrs.Glitter_version = glitter.__version__
        log.root._v_attrs.Glitter_description = glitter.__description__
        log.root._v_attrs.username = ''
        log.root._v_attrs.user_comment = ''
        log.root._v_attrs.video_id = ''
        log.root._v_attrs.creation_time = time.strftime("%A, %B %d, %Y %I:%M:%S %p")
        log.root._v_attrs.logID = self.filetail
        raw_group = log.create_group(log.root, 'raw_data', 'The raw scores and time data. '+
        'There\'s a pts group with the video frame time stamps. There is also a group for each type of '+
        'score. Each score can have multiple lists in it, because each time we seek in the video, '+
        'we create a new list starting from the seeked target, unless we already have the seek target in the list')
        self.raw_group = raw_group
        video_group = log.create_group(log.root, 'video_info', 'Information about the video file.')
        self.video_info_group = video_group
        video_group._v_attrs.file_path = self.filehead
        video_group._v_attrs.file_name = self.filetail
        video_group._v_attrs.video_params = dict(self.media.get_metadata().items() +
                                                 {'width': frame[1][0], 'height': frame[1][1]}.items())
        video_group._v_attrs.seen_all_frames = self.pts_list_complete

        group = log.create_group(raw_group, 'pts', 'lists of the pts corresponding to '+
        'the lists within the other groups in the raw data group.')
        self.pts_group = group
        group = log.create_earray(group, 'pts_0', tb.FloatAtom(), (0,), 'pts')
        group.append((frame[3],))
        # list to the channels. The first index is for each pts group, the
        # second index is for each channel. Only score_types ending with t
        # use more than the first index of the first group.
        # the first element in each second index (element 0) is the pts array
        self.data = [[ group ]]
        self.last_list = self.data[0] # the element of the first index of the pts last used
        self.score_groups = [] # list of all the channels
        # dictionary for each pts value pointing to the element of the first index in data
        # holding the pts, as well as the index within each score for that element for this pts
        self.pts_list = {frame[3]:[self.last_list, 0]}
        for header in headers:
            self.add_header(*header)

    def __del__(self):
        self.close()
        set_log_callback(None)

    def close(self):
        self.media = None
        logging.info('Closing video file %s' % self.filename)
        if self.log_auto:
            if self.unsaved_changes:
                self.log_temp.flush()
                self.log_temp.copy_file(self.log_auto, overwrite=True)
            else:
                self.autosave_writer('')
                os.remove(self.log_auto)
        self.log_auto = None
        self.status_func(complete=False, unsaved=True)
        if self.log_temp:
            filename = self.log_temp.filename
            self.log_temp.close()
            os.remove(filename)
            self.log_temp = None

    def load_log(self, path, overwrite='raise', template=False):
        logfile = path
        filename = os.path.split(os.path.splitext(os.path.normpath(path))[0])[1]
        path = os.path.split(os.path.splitext(os.path.normpath(path))[0])[0]
        autosave_writer = self.autosave_writer
        try:
            log_temp = self.log_temp
            log_temp.copy_file(logfile, overwrite=(overwrite=='overwrite'))
            if not template:
                self.log = logfile
                if self.log_auto_dur:
                    temp_file = tempfile.NamedTemporaryFile(dir=path, prefix=filename+'_', suffix='.autosave', delete=False)
                    temp_name = temp_file.name
                    temp_file.close()
                    log_temp.copy_file(temp_name, overwrite=True)
                    autosave_writer(temp_name)
                    self.log_auto = temp_name
                self.unsaved_changes = False
                self.status_func(unsaved=False)
                if overwrite == 'overwrite':
                    return []
                score_groups = self.score_groups
                res = [None, ] * len(score_groups)
                for col in range(len(score_groups)):
                    settings = {}
                    score_group = score_groups[col]
                    for setting in score_group._v_attrs._f_list('user'):
                        settings[setting] = score_group._v_attrs[setting]
                    res[col] = (col, settings)
                return res
            else:
                template_file = None
                try:
                    template_file = tb.open_file(logfile, 'a')
                    raw_group = template_file.root.raw_data
                    for row in raw_group.pts._f_list_nodes():
                        template_file.remove_node(row, recursive=True)
                    for group in raw_group._f_iter_nodes():
                        if group._v_name == 'pts' or group._v_attrs.score_type != 'xy':
                            for row in group._f_list_nodes():
                                template_file.remove_node(row, recursive=True)
                    return []
                finally:
                    if template_file:
                        template_file.close()
        except IOError as e: # file exits and we don't overwrite
            if overwrite == 'raise' and not len(self.score_groups):
                overwrite = 'load'
            if overwrite == 'raise':
                log = None
                try:
                    log = tb.open_file(logfile)
                    cols = [node._v_name for node in log.root.raw_data._f_iter_nodes() if node._v_name != 'pts']
                finally:
                    if log:
                        log.close()
                raise PyTrackException('log_res', logfile + ' already exists '+
                'with the following columns: [' + ' | '.join(cols) +
                ']. \n\nWhat would you like to do?\n-Load the file and overwrite the current '+
                'channels.\n-Merge the current channels with the file channels.\n-Overwrite the file with '+
                'the current channels (overwrites the file on disk).\n-Browse for another file.\n-Cancel.'
                + '\n\n Module error message:\n' + str(e))
            if overwrite == 'merge' or template:
                if (not template) and not self.pts_list_complete:
                    raise PyTrackException('error',
                                           'Not all frames have been seen yet. You cannot '+
                                           'merge a log until the full video has been seen.')
                if tb.is_pytables_file(logfile):
                    log = None
                    try:
                        log = tb.open_file(logfile)
                        raw_group = log.root.raw_data
                        video_group = log.root.video_info
                        pts_group = raw_group.pts
                        score_groups = [None,] * (raw_group._v_nchildren - 1)
                        settings_list = list(score_groups)
                        res = list(score_groups)
                        for group in raw_group._f_iter_nodes():
                            if group._v_name != 'pts':
                                score_groups[int(group._v_name.rpartition('_')[2])] = group
                        for chan in range(len(score_groups)):
                            settings = {}
                            for setting in score_groups[chan]._v_attrs._f_list('user'):
                                settings[setting] = score_groups[chan]._v_attrs[setting]
                            settings_list[chan] = settings
                        n_pts = len(pts_group._f_list_nodes())
                        data = [[None for j in range(len(score_groups)+1)] for i in range(max(1, n_pts))]
                        for chan in range(len(score_groups)):
                            for row in score_groups[chan]._f_iter_nodes():
                                data[int(row._v_name.rpartition('_')[2])][chan + 1] = row
                        for row in pts_group._f_iter_nodes():
                            data[int(row._v_name.rpartition('_')[2])][0] = row
                        dist_max = 0
                        sorted_pts_list = []
                        pts_list = self.pts_list
                        self.get_closest_pts(sorted_pts_list)
                        for chan in range(len(score_groups)):
                            count = len(self.score_groups)
                            settings = settings_list[chan]
                            self.add_header(count, settings)
                            if settings['score_type'] == 'xy' and data[0][chan+1] and len(data[0][chan+1]):
                                self.add_data_range(count, list(data[0][chan+1]))
                            elif not template:
                                for i in range(len(data)):
                                    for j in range(len(data[i][chan+1]) if data[i][chan+1] else 0):
                                        pts = self.get_closest_pts(sorted_pts_list, data[i][0][j])
                                        dist_max = max(dist_max, abs(pts-data[i][0][j]))
                                        matched_list, matched_idx = pts_list[pts]
                                        matched_list[1+count][matched_idx] = data[i][1+chan][j]
                            res[chan] = count, settings
                    finally:
                        if log:
                            log.close()
                else:
                    with open(logfile, 'r') as csvfile:
                        csvlog = [row for row in csv.reader(csvfile)]
                        if not len(csvlog) or len(csvlog[0]) <= 1:
                            raise Exception("There's nothing to read in the file.")
                        if csvlog[0][0] != 'Time':
                            raise Exception("The first column is time and its title must be Time.")
                        pts = [float(t[0]) for t in csvlog[1:] if t[0]]
                        i = 1
                        channels = []
                        while i < len(csvlog[0]):
                            if csvlog[0][i].startswith('xyt'):
                                if (i+1 >= len(csvlog[0]) or (not csvlog[0][i].startswith('xyt_x_'))
                                    or (not csvlog[0][i+1].startswith('xyt_y_'))):
                                    raise Exception("A xyt score must be a two column series, with the first "+
                                                    "column starting with xyt_x_, and the next column starting with "+
                                                    "xyt_y_. Text following xyt_x_ is the column name.")
                                pos = [(int(t[i]), int(t[i+1])) for t in csvlog[1:] if t[i] and t[i+1]]
                                if len(pos) != len(pts):
                                    raise Exception("Number of data points in a xyt channel must match the number of time points.")
                                sett = TrackLog.get_default_settings('xyt')
                                sett.update({'name':csvlog[0][i][6:]})
                                channels.append((pos, sett))
                                i += 2
                                continue
                            elif csvlog[0][i].startswith('xy'):
                                if (i+1 >= len(csvlog[0]) or (not csvlog[0][i].startswith('xy_x_'))
                                    or (not csvlog[0][i+1].startswith('xy_y_'))):
                                    raise Exception("A xy score must be a two column series, with the first "+
                                                    "column starting with xy_x_, and the next column starting with "+
                                                    "xy_y_. Text following xy_x_ is the column name.")
                                pos = [(int(t[i]), int(t[i+1])) for t in csvlog[1:] if t[i] and t[i+1]]
                                sett = TrackLog.get_default_settings('xy')
                                sett.update({'name':csvlog[0][i][5:]})
                                channels.append((pos, sett))
                                i += 2
                                continue
                            elif csvlog[0][i].startswith('t'):
                                if (not csvlog[0][i].startswith('t_')):
                                    raise Exception("A t score is a column starting with t_. "+
                                                    "Text following t_ is the column name.")
                                vals = [bool(t[i]) for t in csvlog[1:] if t[i]]
                                if len(vals) != len(pts):
                                    raise Exception("Number of data points in a t channel must match the number of time points.")
                                sett = TrackLog.get_default_settings('t')
                                sett.update({'name':csvlog[0][i][2:]})
                                channels.append((vals, sett))
                                i += 1
                                continue
                            else:
                                raise Exception('Column "'+csvlog[0][i]+'" does not match a channel type.')
                    dist_max = 0
                    sorted_pts_list = []
                    res = []
                    pts_list = self.pts_list
                    self.get_closest_pts(sorted_pts_list)
                    for d, settings in channels:
                        count = len(self.score_groups)
                        self.add_header(count, settings)
                        if settings['score_type'] == 'xy':
                            self.add_data_range(count, d)
                        else:
                            for j in range(len(d)):
                                closest_pts = self.get_closest_pts(sorted_pts_list, pts[j])
                                dist_max = max(dist_max, abs(closest_pts-pts[j]))
                                matched_list, matched_idx = pts_list[closest_pts]
                                matched_list[1+count][matched_idx] = d[j]
                        res.append((count, settings))
                logging.warning('The maximum time between the read timestamp and'+
                 'the closest timestamp of this video is %d.' % dist_max)
                return res
            elif overwrite == 'load':
                log = self.log_temp         # overwrite temp file with new file
                log_temp = tb.open_file(logfile)
                res = ''
                #if log_temp.root._v_attrs.Glitter_version != log.root._v_attrs.Glitter_version:
                #    res = "%s version is different than the current program's version" %filename
                if log_temp.root.video_info._v_attrs.file_name != log.root.video_info._v_attrs.file_name:
                    res = "%s video file's name is different than the current video file." %filename
                if log_temp.root.video_info._v_attrs.video_params != log.root.video_info._v_attrs.video_params:
                    res = "%s video file's parameters is different than the current video file's." %filename
                log_temp.close()
                if res:
                    res += ' You might want to merge the file instead.'
                    raise PyTrackException('log_res', res+'\n\n Error message: ' + str(e))
                temp_filename = log.filename
                log.close()
                log = tb.open_file(logfile)
                log.copy_file(temp_filename, overwrite=True)
                log.close()
                self.log = logfile
                log = tb.open_file(temp_filename, 'a')   # open temp
                self.log_temp = log
                if self.log_auto_dur:   # maybe do autosave
                    if self.log_auto:
                        os.remove(self.log_auto)
                    auto_file = tempfile.NamedTemporaryFile(dir=path, prefix=filename+'_', suffix='.autosave', delete=False)
                    auto_name = auto_file.name
                    auto_file.close()
                    log.copy_file(auto_name, overwrite=True)
                    self.log_auto = auto_name
                self.jumped = True  # make sure info is up to date
                log.root._v_attrs.Glitter_version = glitter.__version__
                log.root._v_attrs.Glitter_description = glitter.__description__
                #log.root._v_attrs.username = ''
                #log.root._v_attrs.user_comment = ''
                #log.root._v_attrs.video_id = ''
                log.root._v_attrs.logID = self.filetail
                raw_group = log.root.raw_data
                self.raw_group = raw_group
                video_group = log.root.video_info
                self.video_info_group = video_group
                video_group._v_attrs.file_path = self.filehead
                video_group._v_attrs.file_name = self.filetail
                self.pts_list_complete = video_group._v_attrs.seen_all_frames
                self.pts_group = raw_group.pts

                score_groups = [None,] * (raw_group._v_nchildren - 1)
                for group in raw_group._f_iter_nodes():
                    if group._v_name != 'pts':
                        score_groups[int(group._v_name.rpartition('_')[2])] = group
                self.score_groups = score_groups
                n_pts = len(self.pts_group._f_list_nodes())
                data = [[None for j in range(len(score_groups)+1)] for i in range(n_pts)]
                for col in range(len(score_groups)):
                    for row in score_groups[col]._f_iter_nodes():
                        data[int(row._v_name.rpartition('_')[2])][col + 1] = row
                pts_list = {}
                for row in self.pts_group._f_iter_nodes():
                    segment = int(row._v_name.rpartition('_')[2])
                    data[segment][0] = row
                    for i in range(len(row)):
                        pts_list[row[i]] = [data[segment], i]
                self.data = data
                self.last_list = data[0]
                self.pts_list = pts_list
                res = [None, ] * len(score_groups)
                for col in range(len(score_groups)):
                    settings = {}
                    score_group = score_groups[col]
                    for setting in score_group._v_attrs._f_list('user'):
                        settings[setting] = score_group._v_attrs[setting]
                    res[col] = (col, settings)
                self.unsaved_changes = False
                self.status_func(complete=self.pts_list_complete, unsaved=False)
                if self.log_auto_dur:
                    autosave_writer(auto_name)
                # res must be in increasing chan order
                return res

    def modify_log(self, purpose='autosave'):
        log_auto = self.log_auto
        log = self.log
        if purpose == 'save':
            if not log:
                raise PyTrackException('error', "A log file has not been created.")
            if self.unsaved_changes:
                self.unsaved_changes = False
                self.status_func(unsaved=False)
            self.modify_log()
            self.log_temp.copy_file(log, overwrite=True)
        elif purpose == 'autosave':
            if log_auto:
                self.log_temp.copy_file(log_auto, overwrite=True)
        elif purpose == 'close':
            if log_auto and self.unsaved_changes:
                raise PyTrackException('error', 'You have unsaved changes.')
            if log_auto:
                    self.autosave_writer('')
                    os.remove(log_auto)
                    self.log_auto = ''
                    self.log = ''

    def set_user_info(self, field, value):
        log = self.log_temp
        if field == 'username':
            log.root._v_attrs.username = value
        elif field == 'video_id':
            log.root._v_attrs.video_id = value
        elif field == 'user_comment':
            log.root._v_attrs.user_comment = value

    def get_user_info(self, field):
        log = self.log_temp
        if field == 'username':
            return log.root._v_attrs.username
        elif field == 'video_id':
            return log.root._v_attrs.video_id
        elif field == 'user_comment':
            return log.root._v_attrs.user_comment

    def edit_header(self, chan, settings):
        score_group = self.score_groups
        data = self.data
        if chan >= len(score_group) or not score_group[chan]:
            raise PyTrackException('error',"Column %d doesn't exists." % chan)
        score_group = score_group[chan]
        for key, val in settings.iteritems():
            score_group._v_attrs[key] = val
        score_group._f_rename(settings['name']+'_'+str(chan))
        for i in range(len(data)) if settings['score_type'].endswith('t') else [0]:
            data[i][1 + chan]._f_rename(settings['name']+'_'+str(i))
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.status_func(unsaved=True)

    def add_header(self, chan, settings):
        data = self.data
        score_groups = self.score_groups
        n = len(score_groups)
        log = self.log_temp
        if n > chan:
            if score_groups[chan]:
                raise PyTrackException('error','Column %d already exists.' % chan)
        else:
            for d in data:
                d.extend([None for i in range(1 + chan - n)])
            score_groups.extend([None for i in range(1 + chan - n)])
        group = log.create_group(self.raw_group, settings['name']+'_'+str(chan), settings['name'])
        score_groups[chan] = group
        default_shape = TrackLog.get_default_score_val(settings['score_type'])
        for i in range(len(data)) if settings['score_type'].endswith('t') else [0]:
            data[i][1 + chan] = log.create_earray(group, settings['name']+'_'+str(i), default_shape[0], (0,), settings['name'])
            if settings['score_type'].endswith('t'):
                data[i][1 + chan].append([default_shape[1]] * len(data[i][0]))
        for key, val in settings.iteritems():
            group._v_attrs[key] = val
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.status_func(unsaved=True)

    def delete_header(self, chan):
        score_groups = self.score_groups
        if len(score_groups) > chan and score_groups[chan]:
            self.log_temp.remove_node(score_groups[chan], recursive=True)
            for i in range(chan + 1, len(score_groups)):
                score_groups[i]._f_rename(score_groups[i]._v_attrs['name']+'_'+str(i - 1))
            del score_groups[chan]
            for d in self.data:
                del d[chan+1]
        else:
            raise PyTrackException('error',"Column %d doesn't exists." % chan)
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.status_func(unsaved=True)

    def clear_header(self, chan):
        score_groups = self.score_groups
        if chan == -1:
            for chan in range(len(score_groups)):
                if score_groups[chan]:
                    score_type = score_groups[chan]._v_attrs['score_type']
                    if score_type == 'xy':
                        self.data[0][chan + 1].truncate(0)
                    else:
                        default_val = TrackLog.get_default_score_val(score_type)[1]
                        for d in self.data:
                            for i in range(len(d[chan + 1])):
                                d[chan + 1][i] = default_val
            self.update_notifier()
        else:
            if len(score_groups) > chan and score_groups[chan]:
                score_type = score_groups[chan]._v_attrs['score_type']
                if score_type == 'xy':
                    self.data[0][chan + 1].truncate(0)
                else:
                    default_val = TrackLog.get_default_score_val(score_type)[1]
                    for d in self.data:
                        for i in range(len(d[chan + 1])):
                            d[chan + 1][i] = default_val
                self.update_notifier(chan)
            else:
                raise PyTrackException('error',"Column %d doesn't exists." % chan)
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.status_func(unsaved=True)

    def get_xyt_state(self, chan, anchor_pts, dist, start, line):
        '''start and anchor_pts must not cross a zero point boundary
        and chan must be valid, and a xyt type'''
        pts_list = self.pts_list
        anchor_loc = pts_list[anchor_pts]
        if start is not None:
            start_loc = pts_list[start][1]
        else:
            start_loc = anchor_loc[1]
        def_val = TrackLog.get_default_score_val('xyt')[1]
        dist += anchor_pts
        i = start_loc
        if dist >= anchor_pts:
            try:
                res = all(anchor_loc[0][chan+1][anchor_loc[1]] == def_val)
                is_itr = True
            except TypeError:
                res = anchor_loc[0][chan+1][anchor_loc[1]] == def_val
                is_itr = False
            if res:
                line[:] = []
                return None
            while i < len(anchor_loc[0][0])-1:
                if is_itr:
                    res = anchor_loc[0][0][i+1] > dist or all(anchor_loc[0][chan+1][i+1] == def_val)
                else:
                    res = anchor_loc[0][0][i+1] > dist or anchor_loc[0][chan+1][i+1] == def_val
                if res:
                    break
                i = i + 1
            line[:] = itertools.chain.from_iterable(anchor_loc[0][chan+1][anchor_loc[1]:i+1])
        else:
            try:
                res = not anchor_loc[1] or all(anchor_loc[0][chan+1][anchor_loc[1]-1] == def_val)
                is_itr = True
            except TypeError:
                res = not anchor_loc[1] or anchor_loc[0][chan+1][anchor_loc[1]-1] == def_val
                is_itr = False
            if res:
                line[:] = []
                return None
            if i == anchor_loc[1]:
                while i > 0:
                    if is_itr:
                        res = anchor_loc[0][0][i-1] < dist or all(anchor_loc[0][chan+1][i-1] == def_val)
                    else:
                        res = anchor_loc[0][0][i-1] < dist or anchor_loc[0][chan+1][i-1] == def_val
                    if res:
                        break
                    i = i - 1
            else:
                while i <= anchor_loc[1]:
                    if anchor_loc[0][0][i] >= dist:
                        break
                    i = i + 1
            if is_itr:
                res = 0 if all(anchor_loc[0][chan+1][anchor_loc[1]] == def_val) else 1
            else:
                res = 0 if anchor_loc[0][chan+1][anchor_loc[1]] == def_val else 1
            line[:] = itertools.chain.from_iterable(anchor_loc[0][chan+1][i:anchor_loc[1]+res])
        res = anchor_loc[0][0][i]
        return res

    def get_xy_state(self, chan, line):
        line[:] = itertools.chain.from_iterable(self.data[0][chan+1])

    def get_t_state(self, chan, pts):
        loc = self.pts_list[pts]
        res = loc[0][chan+1][loc[1]]
        return res

    def next_chan_break(self, chan, pts):
        loc = self.pts_list[pts]
        data = self.data
        def_val = TrackLog.get_default_score_val(self.score_groups[chan]._v_attrs.score_type)
        try:
            res = all(loc[0][chan+1][loc[1]] == def_val[1])
            is_itr = True
        except TypeError:
            res = loc[0][chan+1][loc[1]] == def_val[1]
            is_itr = False
        if res:
            compare = operator.ne
        else:
            compare = operator.eq
        # first find the next inverse point of pts
        i = loc[1] + 1
        while i < len(loc[0][0]):
            if is_itr:
                res = all(compare(loc[0][chan+1][i], def_val[1]))
            else:
                res = compare(loc[0][chan+1][i], def_val[1])
            if res:
                break
            i = i + 1
        if i != len(loc[0][0]): # still in the orig list, find start of next segment
            return loc[0][0][i]
        # find the start of the next list
        pos = data.index(loc[0])
        if pos == len(data) - 1:
            return None
        res = data[pos+1][0][0]
        return res

    def get_closest_pts(self, sorted_pts_list, pts=None):
        if pts is None:
            sorted_pts_list[:] = self.pts_list.keys()
            sorted_pts_list.sort()
        else:
            idx = bisect.bisect(sorted_pts_list, pts)
            if idx >= len(sorted_pts_list) or len(sorted_pts_list) == 1:
                return sorted_pts_list[idx-1]
            if sorted_pts_list[idx] - pts < pts - sorted_pts_list[idx-1]:
                return sorted_pts_list[idx]
            else:
                return sorted_pts_list[idx-1]

    def get_prev_pts(self, pts):
        pts_list = self.pts_list
        try:
            pos = pts_list[pts]
        except KeyError:
            sorted_list = []
            self.get_closest_pts(sorted_list)
            pos = self.get_closest_pts(sorted_list, pts)
            pos = pts_list[pos]
        t = None
        if pos[1]:
            t = pos[0][0][pos[1]-1]
        else:
            data = self.data
            idx = data.index(pos[0])
            if idx:
                t = data[idx-1][0][-1]
        return t

    def add_data_point(self, chan, val, pts=None):
        score_group = self.score_groups[chan]
        if score_group._v_attrs.score_type.endswith('t'):
            pts_list = self.pts_list[pts]
            pts_list[0][chan + 1][pts_list[1]] = val
        else:
            self.data[0][chan + 1].append([val])
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.status_func(unsaved=True)

    def add_data_range(self, chan, val, pts_start=None, pts_end=None):
        score_group = self.score_groups[chan]
        if score_group._v_attrs.score_type.endswith('t'):
            pts_list_start = self.pts_list[pts_start]
            pts_list_end = self.pts_list[pts_end]
            if pts_list_start[0] != pts_list_end[0]:
                return
            for i in range(pts_list_start[1], pts_list_end[1]+1):
                pts_list_start[0][chan + 1][i] = val
        else:
            self.data[0][chan + 1].append(val)
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.status_func(unsaved=True)

    def get_data_point(self, chan, pts):
        score_group = self.score_groups[chan]
        if score_group._v_attrs.score_type.endswith('t'):
            pts_list = self.pts_list[pts]
            res = pts_list[0][chan + 1][pts_list[1]]
        else:
            res = list(self.data[0][chan + 1])
        return res

    def is_data_default(self, chan, pts):
        value = self.get_data_point(chan, pts)
        def_val = TrackLog.get_default_score_val(self.score_groups[chan]._v_attrs.score_type)
        try:
            return all(value == def_val[1])
        except TypeError:
            return value == def_val[1]

    def get_pts_lists(self):
        return [section[0][:] for section in self.data]

    def get_video_metadata(self, key):
        if key == 'size':
            return self.frame_size
        elif key == 'duration':
            return self.duration

    def get_export_list(self):
        output = []
        output.append('_version')
        output.append('_filename')
        output.append('_vid_info')
        output.append('_username')
        output.append('_video_id')
        output.append('_user_comment')
        output.append('_ID')
        output.append('_complete')
        output.append('_pts')
        for group in self.log_temp.root.raw_data._f_iter_nodes():
            if group._v_name != 'pts':
                output.append(group._v_name.rpartition('_')[0])
                output.append(group._v_name)
        return list(set(output))

    def get_next_frame(self):
        if self.cached_frame:
            frame = self.cached_frame
            self.cached_frame = None
            return frame
        try:
            frame, val = self.media.get_frame()
            while (not frame) and val != 'eof' and val != 'pause':
                time.sleep(0.1)
                frame, val = self.media.get_frame()
            if val == 'eof':
                raise EOFError()
            elif val == 'pause':
                raise Exception("We're paused for some unfathomable reason.")

            # the following is used to built up the list of pts for the frames
            if not self.pts_list_complete:
                pts_list = self.pts_list
                last_list = self.last_list
                data = self.data
                score_groups = self.score_groups
                log = self.log_temp
                if frame[3] not in pts_list: # new time point we haven't seen before
                    if self.jumped: # if we jumped add a new list for target if it doesn't exists yet.
                        pos = 0
                        for d in data:
                            if frame[3] < d[0][0]:
                                break
                            pos += 1
                        for i in range(len(data)-1, pos-1, -1):
                            for j in range(1, len(data[i])):
                                if data[i][j]:
                                    data[i][j]._f_rename(score_groups[j-1]._v_attrs.name+'_'+str(i+1))
                            data[i][0]._f_rename('pts'+'_'+str(i+1))

                        last_list = [None, ] * len(data[0])
                        for i in range(1, len(last_list)):
                            default_shape = TrackLog.get_default_score_val(score_groups[i-1]._v_attrs.score_type)
                            if score_groups[i-1]._v_attrs.score_type.endswith('t'):
                                last_list[i] = log.create_earray(score_groups[i-1], score_groups[i-1]._v_attrs.name+'_'+str(pos), default_shape[0], (0,), score_groups[i-1]._v_attrs.name)
                        last_list[0] = log.create_earray(self.pts_group, 'pts'+'_'+str(pos), tb.FloatAtom(), (0,), 'pts')
                        data.insert(pos, last_list)
                        self.jumped = False
                        self.last_list = last_list
                    for i in range(1, len(data[0])):
                        default_shape = TrackLog.get_default_score_val(score_groups[i-1]._v_attrs.score_type)
                        if score_groups[i-1]._v_attrs.score_type.endswith('t'):
                            last_list[i].append([default_shape[1]])
                    last_list[0].append((frame[3],))
                    pts_list[frame[3]] = [last_list, len(last_list[0]) - 1]
                    self.edit_pts_break_func(last_list[0][:], pts_new=frame[3])
                    if not self.unsaved_changes:
                        self.unsaved_changes = True
                        self.status_func(unsaved=True)
                else:
                    curr_list = pts_list[frame[3]]
                    curr_pos = curr_list[1]
                    curr_list = curr_list[0]
                    if self.jumped:
                        self.last_list = curr_list
                        self.jumped = False
                    else:
                        # we just past the end of one list into another, combine them
                        if curr_list is not last_list:
                            curr_idx = data.index(curr_list)
                            if data[curr_idx - 1] is not last_list or curr_pos:
                                raise PyTrackException('error','Something went wrong with pts monotonicity: contact the developers with this video.')
                            last_len = len(last_list[0])
                            for i in range(len(last_list)): # merge data
                                if last_list[i] and curr_list[i]:
                                    last_list[i].append(curr_list[i][:])
                            for d in curr_list:
                                if d:
                                    log.remove_node(d, recursive=True)
                            for i in range(curr_idx+1, len(data)):  # rename sub-channels
                                for j in range(1, len(data[i])):
                                    if data[i][j]:
                                        data[i][j]._f_rename(score_groups[j-1]._v_attrs.name+'_'+str(i-1))
                                data[i][0]._f_rename('pts'+'_'+str(i-1))
                            for i in range(last_len, len(last_list[0])):
                                pts_list[last_list[0][i]] = [last_list, i]
                            del data[curr_idx]
                            self.edit_pts_break_func(last_list[0][:])
                            if not self.unsaved_changes:
                                self.unsaved_changes = True
                                self.status_func(unsaved=True)
#                     # now check whether we have all the frames
#                     total = 0
#                     for d in data:
#                         total += len(d[0])
#                     if total == self.num_frames and len(data) == 1:
#                         self.pts_list_complete = True
        except EOFError:
            if len(self.data) == 1 and not self.pts_list_complete:
                self.pts_list_complete = True
                self.video_info_group._v_attrs.seen_all_frames = True
                self.unsaved_changes = True
                self.status_func(complete=True)
                self.edit_pts_break_func()
            raise
        return frame

    def seek_to_pts(self, pts):
        self.media.seek(pts, relative=False)
        self.jumped = True
