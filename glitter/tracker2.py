
import os
import logging
import sys
import itertools
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
