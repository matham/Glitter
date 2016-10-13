import kivy
import sys
import os
from os.path import sep
import time
import colorsys
import bisect
import re
import traceback
from functools import partial
from math import log10, floor, sin, cos, atan, radians, sqrt

from kivy.config import Config
Config.set('kivy', 'exit_on_escape', 0)
kivy.require('1.8.0')
from kivy.base import EventLoop
EventLoop.ensure_window()
from kivy.uix.widget import Widget
from kivy.app import App
from kivy.properties import NumericProperty, ReferenceListProperty, ObjectProperty,\
ListProperty, StringProperty, BooleanProperty, ListProperty, DictProperty
from kivy.clock import Clock
Clock.max_iteration = 20
from kivy.uix.slider import Slider
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.popup import Popup
from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle, Color, Line, Mesh, Quad
from kivy.graphics.instructions import InstructionGroup
from kivy.graphics.transformation import Matrix
from kivy.core.window import Window
from kivy.uix.togglebutton import ToggleButton
from kivy.config import ConfigParser
from kivy.compat import PY2
from tracker import TrackLog
from kivy.garden.filebrowser import FileBrowser
from kivy.garden.tickmarker import TickMarker
from misc import PyTrackException, PyTrackPopups
from kivy.uix.behaviors import DragBehavior
import logging
from kivy.logger import Logger, FileHandler as kivy_handler
logging.root= Logger

import tracker
# import the exporter at the exe location only if it's present
if getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(sys.executable))
try:
    import exporter
except ImportError:
    logging.warning('The exporter module was not found.')
if getattr(sys, 'frozen', False):
    del sys.path[0]


def str_to_float(strnum, minval, maxval, err_max=True):
    try:
        val= float(strnum)
    except:
        val= maxval if err_max else minval
    if val < minval or val > maxval:
        val= maxval if err_max else minval
    return val

def printt(*args):
    print args
    return True

class DragPopup(DragBehavior, Popup): pass
class MainFrame(BoxLayout): pass
class PopupBrowser(DragPopup): pass
class ErrorInfo(DragPopup):
    res_func = ObjectProperty(None, allownone=True)
class ColorSelector2(DragPopup): pass
class UserInfo(DragPopup): pass
class TickSlider(Slider, TickMarker): pass


class PathButton(RelativeLayout):
    ''' The button used for the xy, xyt, and t type scoring.
    Each button holds the settings for its channel and varies by score type.
    '''

    down_color = ListProperty([1, 1, 1, 1])
    default_color = ListProperty([1, 1, 1, 1])
    comp_color = ListProperty([1, 1, 1, 1])
    name = StringProperty('')
    activated = BooleanProperty(False)
    settings = DictProperty({})
    display = DictProperty({})
    more_text = StringProperty('')

class XYTSettings(BoxLayout):

    def get_settings(self):
        return {'name':self.ids['text_name'].text,
                'plot':self.ids['show_graph'].state == 'down',
                'color':self.wheel.color[:]}

    def set_settings(self, kargs):
        self.ids['text_name'].text = kargs['name']
        self.ids['show_graph'].state = 'down' if kargs['plot'] else 'normal'
        self.wheel.color[:] = kargs['color']

class XYSettings(BoxLayout):
    def get_settings(self):
        return {'name':self.ids['text_name'].text,
                'color':self.wheel.color[:]}

    def set_settings(self, kargs):
        self.ids['text_name'].text = kargs['name']
        self.wheel.color[:] = kargs['color']

class TSettings(BoxLayout):

    def get_settings(self):
        if self.ids['event'].state == 'down':
            event = 'event'
        elif self.ids['toggle'].state == 'down':
            event = 'toggle'
        else:
            event = 'press'
        return {'name':self.ids['text_name'].text, 'event_type':event,
                'plot':self.ids['show_graph'].state == 'down',
                'keycode':self.ids['keycode'].text, 'color':self.wheel.color[:],
                'group':self.ids['group'].text}

    def set_settings(self, kargs):
        self.ids['text_name'].text = kargs['name']
        self.ids['keycode'].text = kargs['keycode']
        self.ids['group'].text = kargs['group']
        self.ids['show_graph'].state = 'down' if kargs['plot'] else 'normal'
        self.ids['event'].state = 'normal'
        self.ids['press'].state = 'normal'
        self.ids['toggle'].state = 'normal'
        self.ids[kargs['event_type'] if kargs['event_type'] else 'press'].state = 'down'
        self.wheel.color[:] = kargs['color']

class BufferImage(Widget):
    effect_width = NumericProperty(0)
    effect_height = NumericProperty(0)

    def __init__(self, **kwargs):
        super(BufferImage, self).__init__(**kwargs)
        self.img_texture = None
        self.frame_size = 100, 100

    def set_texture_size(self, frame_size, reload_buff_func):
        self.frame_size = frame_size
        self.size = frame_size
        self.img_texture = Texture.create(size=self.frame_size)
        self.img_texture.flip_vertical()
        self.reload_buff_func = reload_buff_func
        self.img_texture.add_reload_observer(self.reload_buffer)
        self.canvas.remove_group(str(self)+'image_display')
        with self.canvas:
            Color(group=str(self)+'image_display')
            Rectangle(texture=self.img_texture, pos=self.pos, size=self.frame_size,
                      group=str(self)+'image_display')
        Clock.schedule_once(partial(self.rescale, 0))

    def rescale(self, rotation=0, *largs):
        if (not self.effect_height) or (not self.effect_width) or not self.img_texture:
            return
        rotation += int(self.parent.rotation)
        rotation %= 360
        self.parent.transform = Matrix()
        init_theta = atan(self.frame_size[1] / float(self.frame_size[0]))
        curr_theta_offset = radians(rotation)
        arc = sqrt(self.frame_size[1]**2 + self.frame_size[0]**2)/2.
        height = 2 * arc * max(abs(sin(curr_theta_offset+init_theta)), abs(sin(curr_theta_offset-init_theta)))
        width = 2 * arc * max(abs(cos(curr_theta_offset+init_theta)), abs(cos(curr_theta_offset-init_theta)))
        init_h_diff = height - self.frame_size[1]
        init_w_diff = width - self.frame_size[0]
        scale = min(self.effect_height / float(height),
                    self.effect_width / float(width))
        offset_width = (width * (scale - 1) + init_w_diff) / 2.
        offset_height = (height * (scale - 1) + init_h_diff) / 2. + max(0, self.effect_height - height * scale)

        r = Matrix().scale(scale, scale, 1).rotate(curr_theta_offset, 0, 0, 1)\
        .translate(offset_width, offset_height, 0)
        self.parent.apply_transform(r, anchor=self.center)
        self.parent.canvas.ask_update()

    def set_texture(self, buff):
        self.img_texture.blit_buffer(buff, colorfmt='rgb', bufferfmt='ubyte')

    def reload_buffer(self, *args):
        buff= self.reload_buff_func()
        if buff:
            self.set_texture(buff)



class TrackApp(App):
    filename = StringProperty()
    path_bar_w = ObjectProperty(None)
    main_frame_w = ObjectProperty(None)
    xyt_buttons_w = ObjectProperty(None)
    xy_buttons_w = ObjectProperty(None)
    t_buttons_w = ObjectProperty(None)
    pause_btn_w = ObjectProperty(None)
    seek_slider_w = ObjectProperty(None)
    rate_w = ObjectProperty(None)
    img_scatter_w = ObjectProperty(None)
    img_w = ObjectProperty(None)
    path_bar_w = ObjectProperty(None)
    status_bar_w = ObjectProperty(None)
    img_screen_w = ObjectProperty(None)
    edit_screen_w = ObjectProperty(None)
    xyt_graph_w = ObjectProperty(None)
    t_graph_w = ObjectProperty(None)
    seek_bar_w = ObjectProperty(None)
    cut_t_button_w = ObjectProperty(None)
    prog_log_w = ObjectProperty(None)
    xyt_plot_w = ObjectProperty(None)
    t_plot_w = ObjectProperty(None)
    export_btns_w = ObjectProperty(None)
    export_code_w = ObjectProperty(None)
    export_output_w = ObjectProperty(None)
    browse_w = ObjectProperty(None)
    user_comment_w = ObjectProperty(None)
    settings_screen_w = ObjectProperty(None)
    rate_text_w = ObjectProperty(None)
    export_n_text_w = ObjectProperty(None)

    curr_export_btn = ObjectProperty(None, allownone=True)

    prog_log = StringProperty('')
    tracks_list = ListProperty([])
    mode = StringProperty('')
    curr_edit_score = ObjectProperty(None, allownone=True)
    curr_score = ObjectProperty(None, allownone=True)
    keyboard_active = BooleanProperty(True)

    control_text_height = NumericProperty(10)
    add_button_height = NumericProperty(60)
    path_fwd_tint = NumericProperty(0.33)
    max_points= NumericProperty(100)
    seeking_dist= NumericProperty(8.0)
    frame_rate= NumericProperty(1)
    start_time = NumericProperty(0)
    xyt_fwd_dur = NumericProperty(2)
    xyt_bkwd_dur = NumericProperty(-2)
    end_time = NumericProperty(sys.maxsize)
    default_data_path = StringProperty('')
    autosave_file = StringProperty('')
    autosave_time = NumericProperty(5)
    last_vid_path = StringProperty('')
    last_data_path = StringProperty('')


    def __init__(self, **kwargs):
        super(TrackApp, self).__init__(**kwargs)
        self.icon = 'media/Dancing rats_clean.png'
        self.about_info = '''
        Interactive video analysis (CPL Lab v2.1)

        "And above all, watch with glittering eyes the whole world around you
        because the greatest secrets are always hidden in the most unlikely places."

        -- Roald Dahl
        '''
        self.zooming= False # true when the ctrl is held down so we can zoom image
        self.file_browser = None
        self.score_dict = {}#{-1:(None, None, '')}
        self.keycode_dict = {}
        self.keycode_dict_inv = {}
        self.score_dict_inv = {} #{None:(-1, '')}
        self.score_count = 0
        self.t_btn_groups = {}
        self.t_btn_groups_inv = {}
        self.shift_is_pressed = False
        self.t_type_subscript = {'event':'[i][size=22][sup]E[/sup][/size][/i]',
                                 'press':'[i][size=22][sup]P[/sup][/size][/i]',
                                 'toggle':'[i][size=22][sup]T[/sup][/size][/i]'}
        self.frame_rate= 1
        self.add_button_height = 60
        self.path_fwd_tint = 0.33
        self.max_points= 100
        self.start_paused= 1
        self.seeking_dist= 8.0
        self.limit_range = 0
        self.start_time = 0
        self.end_time = sys.maxsize
        self.plot_pixel_width = 2
        self.plot_pixel_height = 6
        self.plot_use_contrast = 0
        self.load_default_data = 1
        self.username = ''
        self.user_comment = ''
        self.video_id = ''
        self.numpad_list = ['numpad' + str(i) for i in range(10)]

        self.initialize()
        self.home_dir = os.path.expanduser('~')
        if getattr(sys, 'frozen', False):
            app_path = os.path.dirname(sys.executable)
        elif __file__:
            app_path = os.path.dirname(__file__)
        else:
            app_path = ''
        self.app_path = app_path

        self.config_track = ConfigParser()
        self.config_sys = ConfigParser()
        config_path = os.path.join(self.app_path, 'glitter.ini')
        if not os.path.exists(config_path):
            with open(config_path, 'w'):
                pass
        self.config_track.read(config_path)
        self.verify_settings()
        self.config_track.write()
        config_path = os.path.join(self.app_path, 'glitter_internal.ini')
        if not os.path.exists(config_path):
            with open(config_path, 'w'):
                pass
        self.config_sys.read(config_path)
        config = self.config_sys
        if not config.has_section('glitter'):
            config.add_section('glitter')
        if not config.has_option('glitter', 'autosave_file'):
            config.set('glitter', 'autosave_file', self.autosave_file)
        config.write()
        options = self.config_track.options('glitter')
        for option in options:
            self.edit_setting(None, option, self.config_track.get('glitter', option))
        self.config_track.add_callback(self.edit_setting)

    def initialize(self):
        self.media= None
        self.last_frame = None
        self.next_frame = None
        self.duration= 100
        self.started= False
        self.frame_num= 0
        self.touch= None
        self.filename =''
        self.full_filename = ''
        self.data_filename = ''
        self.pts_complete = False
        self.data_unsaved = True
        self.xy_state = None
        self.seeked = False
        self.released_touch = None
        self.plot_pts_list = []
        self.plot_pts_breaks = []
        self.plot_pts_dups = []

        self.export_filename = ''
        self.export_file = None

        self.set_tittle()

        for btn in self.score_dict_inv:
            if btn.settings['score_type'].endswith('t'):
                for quad_ctx, quad_list in ((btn.plot_group_ctx, btn.quad_list),
                                            (btn.plot_comp_group_ctx, btn.quad_comp_list),
                                            (btn.plot_mix_group_ctx, btn.quad_mix_list)):
                    for quad in quad_list:
                        quad_ctx.remove(quad)
                    del quad_list[:]

    def verify_settings(self):
        config = self.config_track
        if not config.has_section('glitter'):
            config.add_section('glitter')
        config_option = ('add_button_height', 'plot_pixel_width', 'plot_pixel_height',
                         'plot_use_contrast', 'max_points', 'path_fwd_tint',
                         'xyt_fwd_dur', 'xyt_bkwd_dur', 'seeking_dist', 'frame_rate',
                         'start_time', 'end_time', 'start_paused', 'limit_range',
                         'default_data_path', 'load_default_data', 'autosave_time',
                         'last_vid_path', 'last_data_path', 'user_comment',
                         'username', 'video_id')
        for option in config_option:
            if not config.has_option('glitter', option):
                config.set('glitter', option, str(getattr(self, option)))

    def edit_setting(self, section, key, value):
        if key == 'add_button_height':
            self.add_button_height = abs(int(value))
        elif key == 'plot_pixel_width':
            self.plot_pixel_width = max(abs(int(value)), 1)
            self.update_plot()
        elif key == 'plot_pixel_height':
            self.plot_pixel_height = max(abs(int(value)), 3)
            self.update_plot()
        elif key == 'plot_use_contrast':
            self.plot_use_contrast = bool(float(value))
            self.update_plot()
        elif key == 'max_points':
            self.max_points = abs(int(value))
        elif key == 'path_fwd_tint':
            self.path_fwd_tint = abs(float(value))
        elif key == 'xyt_fwd_dur':
            self.xyt_fwd_dur = abs(float(value))
            self.notify_chan_update()
        elif key == 'xyt_bkwd_dur':
            self.xyt_bkwd_dur = float(value)
            if self.xyt_bkwd_dur > 0:
                self.xyt_bkwd_dur = -self.xyt_bkwd_dur
            self.notify_chan_update()
        elif key == 'seeking_dist':
            self.seeking_dist = abs(float(value))
        elif key == 'user_comment':
            self.user_comment = value
        elif key == 'username':
            self.username = value
        elif key == 'video_id':
            self.video_id = value
        elif key == 'frame_rate':
            self.frame_rate = abs(float(value))
        elif key == 'start_time':
            self.start_time = float(value)
        elif key == 'end_time':
            self.end_time = float(value)
        elif key == 'start_paused':
            self.start_paused = bool(float(value))
        elif key == 'limit_range':
            self.limit_range = bool(float(value))
        elif key == 'default_data_path':
            if not value:
                self.default_data_path = ''
            else:
                path = os.path.normpath(os.path.expanduser(value))
                self.default_data_path = path if os.path.isdir(path) else self.home_dir
        elif key == 'load_default_data':
            self.load_default_data = bool(float(value))
        elif key == 'autosave_time':
            self.autosave_time = abs(float(value))
            if self.media:
                Clock.unschedule(self.media.modify_log)
                if self.autosave_time and self.data_filename:
                    Clock.schedule_interval(self.media.modify_log, self.autosave_time)
        elif key == 'last_vid_path':
            if not value:
                value = ' '
            path = os.path.normpath(os.path.expanduser(value))
            self.last_vid_path = path if os.path.isdir(path) else self.home_dir
        elif key == 'last_data_path':
            if not value:
                value = ' '
            path = os.path.normpath(os.path.expanduser(value))
            self.last_data_path = path if os.path.isdir(path) else self.home_dir
        self.config_track.write()

    def set_last_path(self, path_type):
        value = self.file_browser.content.ids.tabbed_browser.get_current_tab().content.path
        if not value:
            value = ' '
        path = os.path.normpath(os.path.expanduser(value))
        value = path if os.path.isdir(path) else self.home_dir
        config = self.config_track
        if path_type == 'data':
            config.set('glitter', 'last_data_path', value)
            self.last_data_path = value
        else:
            config.set('glitter', 'last_vid_path', value)
            self.last_vid_path = value
        config.write()
        return True

    def get_last_path(self, path_type):
        return self.last_data_path if path_type == 'data' else self.last_vid_path

    def set_user_info(self, field, value):
        if field == 'username':
            self.config_track.set('glitter', 'username', value)
            self.username = value
        elif field == 'video_id':
            self.config_track.set('glitter', 'video_id', value)
            self.video_id = value
        elif field == 'user_comment':
            self.config_track.set('glitter', 'user_comment', value)
            self.user_comment = value
        if self.media:
            self.media.set_user_info(field, value)
        self.config_track.write()

    def build(self):
        back = MainFrame()
        self.file_browser = PopupBrowser()
        self.color_selector= ColorSelector2()
        self.user_comment_w = UserInfo()
        self.error_popup= ErrorInfo()
        return back

    def on_start(self):
        self.keyboard = Window.request_keyboard(None, self.img_w)
        self.keyboard.ignored_events = []
        self.keyboard.bind(on_key_down=self.on_keyboard_down)
        self.keyboard.bind(on_key_up=self.on_keyboard_up)
        self.set_tittle()
        self.update_plot()
        autosave = self.config_sys.get('glitter', 'autosave_file')
        if autosave and os.path.exists(autosave):
            Clock.schedule_once(partial(self.recover_data, 'notify'), 0)
        def update_export_label(*largs):
            if self.curr_export_btn:
                self.curr_export_btn.export_code = self.export_code_w.text
        self.export_code_w.bind(text=update_export_label)

    def set_tittle(self, unsaved=None, complete=None):
        if unsaved is not None:
            self.data_unsaved = unsaved
        if complete is not None:
            self.pts_complete = complete
        title = 'Video Scoring Package.'
        if not self.pts_complete:
            title += ' (#)'
        if self.data_unsaved:
            title += '*'
        if self.full_filename:
            title += ' - ' + self.full_filename + ' '
        if self.data_filename:
            title += '(' + self.data_filename + ').'
        Window.set_title(title)

    def set_autosave_file(self, filename=''):
        self.config_sys.set('glitter', 'autosave_file', filename)
        self.config_sys.write()

    def recover_data(self, purpose='result', action='save'):
        if purpose == 'notify':
            self.exception_handler('The program closed unexpectedly '+
            'previously. The following autosaved data file has been recovered: ' +
            self.config_sys.get('glitter', 'autosave_file') + '. \n\nWhat would '+
            'you like to do with it - delete it, or save it?', self.recover_data,
            'recover_autosave', 'File recovered.')
        elif purpose == 'result':
            filename = self.config_sys.get('glitter', 'autosave_file')
            if action == 'save':
                try:
                    os.rename(filename, filename+'.saved')
                    self.set_autosave_file()
                except:
                    pass
            elif action == 'delete':
                try:
                    os.remove(filename)
                except:
                    pass
                self.set_autosave_file()
            else:
                pass

    def on_keyboard_down(self, keyboard, keycode, text, modifiers):
        if (self.export_code_w.focus or self.export_n_text_w.focus or
            self.rate_text_w.focus or not self.keyboard_active):
            self.keyboard.ignored_events.append(keyboard.uid)
            return False
        if keycode[1] == 'o' and 'ctrl' in modifiers:
            # this can work when kivy templates become less crappy.
            pass
            #self.browse_bar_w.video_popup.popupp.open()
        elif keycode[1] == 'l' and 'ctrl' in modifiers:
            pass
            #self.browse_bar_w.data_popup.popupp.open()
        elif keycode[1] == 's' and 'ctrl' in modifiers:
            self.update_data('save')
        elif keycode[1] == 'shift':
            self.img_scatter_w.do_translation=  (True, True)
            self.img_scatter_w.do_scale=  True
            self.zooming= True
            self.shift_is_pressed = True
        elif keycode[1] == 'right':
            if self.started:
                if self.frame_rate:
                    self.seek_to_pts(relative=1.0)
                else:
                    self.get_next_frame()
        elif keycode[1] == 'left':
            if self.started:
                if self.frame_rate:
                    self.seek_to_pts(relative=-1.0)
                else:
                    prev = self.media.get_prev_pts(self.last_pts)
                    if prev:
                        self.seek_to_pts(prev)
        elif keycode[1] == 'up':
            self.rate_w.value = min(1.0, log10(1.1*(10**self.rate_w.value)))
        elif keycode[1] == 'delete':
            self.cut_t_button_w.state = 'down'
            if self.curr_score:
                self.update_t_states(self.curr_score)
        elif keycode[1] == 'down':
            self.rate_w.value = max(-2.01, log10((10**self.rate_w.value)/1.1))
        elif keycode[1] == 'spacebar':
            if self.pause_btn_w.state == 'down':
                self.unpause()
            else:
                self.pause()
        elif keycode[1] == 'd' and 'ctrl' in modifiers:
            self.seek_bar_w.delete_btn.state = 'down'
            self.seek_bar_w.clear_btn.state = 'normal'
            self.seek_bar_w.activate_btn.state = 'normal'
            self.seek_bar_w.edit_btn.state = 'normal'
            self.mode = 'delete'
        elif keycode[1] == 'c' and 'ctrl' in modifiers:
            self.seek_bar_w.clear_btn.state = 'down'
            self.seek_bar_w.delete_btn.state = 'normal'
            self.seek_bar_w.activate_btn.state = 'normal'
            self.seek_bar_w.edit_btn.state = 'normal'
            self.mode = 'clear'
        elif keycode[1] == 'a' and 'ctrl' in modifiers:
            self.seek_bar_w.activate_btn.state = 'down'
            self.seek_bar_w.clear_btn.state = 'normal'
            self.seek_bar_w.delete_btn.state = 'normal'
            self.seek_bar_w.edit_btn.state = 'normal'
            self.mode = 'activate'
        elif keycode[1] == 'e' and 'ctrl' in modifiers:
            self.seek_bar_w.edit_btn.state = 'down'
            self.seek_bar_w.clear_btn.state = 'normal'
            self.seek_bar_w.delete_btn.state = 'normal'
            self.seek_bar_w.activate_btn.state = 'normal'
            self.mode = 'edit'
        elif keycode[1] == 'escape':
            self.seek_bar_w.clear_btn.state = 'normal'
            self.seek_bar_w.delete_btn.state = 'normal'
            self.seek_bar_w.activate_btn.state = 'normal'
            self.seek_bar_w.edit_btn.state = 'normal'
            self.curr_score = None
            self.xy_state = None
            self.browse_w.ids.settings_btn.state = 'normal'
            self.browse_w.ids.dancing_btn.state = 'normal'
            self.browse_w.ids.export_btn.state = 'normal'
            self.img_screen_w.current = 'image'
            self.mode = ''
        elif keycode[1] == 'right' and 'ctrl' in modifiers:
            self.seek_to_next_break()
        elif keycode[1] in self.keycode_dict or (keycode[1] in self.numpad_list\
        and keycode[1][-1] in self.keycode_dict):
            btn = self.keycode_dict[keycode[1][-1]]
            if btn[1] == 'off':
                self.keycode_dict[keycode[1][-1]] = btn[0], 'on'
                btn[0].key_touching = True
                self.score_button_press(btn[0], 'press', virtual=True)
        else:
            return False
        return True

    def on_keyboard_up(self, keyboard, keycode):
        if keyboard.uid in self.keyboard.ignored_events:
            self.keyboard.ignored_events.remove(keyboard.uid)
            return False
        if keycode[1] == 'shift':
            if self.mode != 'edit':
                self.img_scatter_w.do_translation=  (False, False)
                self.img_scatter_w.do_scale=  False
                self.zooming= False
            self.shift_is_pressed = False
        elif keycode[1] == 'delete' and not self.cut_t_button_w.pressing:
            self.cut_t_button_w.state = 'normal'
        elif keycode[1] in self.keycode_dict or (keycode[1] in self.numpad_list\
        and keycode[1][-1] in self.keycode_dict):
            btn = self.keycode_dict[keycode[1][-1]]
            if btn[1] == 'on':
                self.keycode_dict[keycode[1][-1]] = btn[0], 'off'
                btn[0].key_touching = False
                self.score_button_press(btn[0], 'release', virtual=True)
        else:
            return False
        return True

    def touch_down(self, touch):
        if self.started and self.img_w.collide_point(*touch[1].pos) and not self.zooming:
            xy_state = self.xy_state
            if xy_state:
                self.touch = None
                self.media.add_data_point(self.score_dict_inv[self.curr_score][0], touch[1].pos)
                self.update_line(btn=xy_state)
            else:
                self.touch= touch[1].pos
        else:
            self.touch = None
        self.released_touch = None

    def touch_move(self, touch):
        if self.started and self.img_w.collide_point(*touch[1].pos) and not self.zooming:
            xy_state = self.xy_state
            if self.xy_state:
                self.media.add_data_point(self.score_dict_inv[self.curr_score][0], touch[1].pos)
                self.update_line(btn=xy_state)
            elif self.frame_rate or self.touch:
                self.touch= touch[1].pos
        else:
            self.touch = None
            self.released_touch = None

    def touch_up(self, touch):
        if self.started and self.img_w.collide_point(*touch[1].pos) and self.pause_btn_w.state != 'down':
            if not self.frame_rate:
                Clock.schedule_once(self.get_next_frame, 0.001)
            self.released_touch = self.touch
            self.touch= None
        else:
            self.released_touch = None
            self.touch= None


    def load_video(self, filename, *args):
        self.close_video()
        try:
            self.media= TrackLog(filename, self.get_all_buttons(), self.autosave_time,
                                 self.set_tittle, self.set_autosave_file,
                                 self.notify_chan_update, self.edit_plot_breaks)
            self.duration= self.media.get_video_metadata('duration')
            self.seek_slider_w.range= (0, self.duration)
            self.update_plot()
            if self.limit_range:
                self.media.seek_to_pts(self.start_time)
        except Exception as e:
            logging.warning(traceback.format_exc())
            self.exception_handler(str(e), None, 'error', 'Error!')
            self.media= None
            return False
        Clock.unschedule(self.media.modify_log)
        if self.autosave_time:
            Clock.schedule_interval(self.media.modify_log, self.autosave_time)
        self.filename = os.path.basename(filename)
        self.full_filename = filename
        self.set_tittle()
        self.img_w.set_texture_size(self.media.get_video_metadata('size'), self.last_buffer)
        frame = self.media.get_next_frame()
        self.last_frame = frame
        self.last_pts = frame[3]
        self.seek_slider_w.value = self.last_pts
        self.img_w.set_texture(frame[0])
        self.next_frame = self.media.get_next_frame()
        self.notify_chan_update()
        self.started = True
        self.seeked = True
        if self.start_paused:
            self.pause_btn_w.state = 'down'
        if self.frame_rate and self.pause_btn_w.state != 'down':
            Clock.schedule_once(self.get_next_frame, (self.next_frame[3] - frame[3])/self.frame_rate)
        if self.load_default_data:
            vid_file = os.path.split(os.path.splitext(os.path.normpath(filename))[0])
            path = self.default_data_path if self.default_data_path else vid_file[0]
            self.load_data(path + sep + vid_file[1] + '.h5')
        return True

    def load_data(self, filename, overwrite='raise', template=False):
        self.pause()
        if self.media:
            if ((not filename.endswith('.h5')) and (not filename.endswith('.plt'))
                 and (not filename.endswith('.saved')) and not filename.endswith('.txt')
                  and not filename.endswith('.csv')):
                filename += '.h5' if not template else '.plt'
            if filename.endswith('.txt') or filename.endswith('.csv'):
                overwrite = 'merge'
            try:
                if (filename.endswith('.txt') or filename.endswith('.csv')) and not os.path.isfile(filename):
                    raise Exception("File doesn't exist")
                headers = self.media.load_log(filename, overwrite, template)
            except Exception as e:
                logging.warning(traceback.format_exc())
                msg = str(e) + '\n' + traceback.format_exc()
                if e.__class__ != PyTrackException or e.exception_type == 'error':
                    self.exception_handler(msg, None, 'error', 'Error!', delay=True)
                else:
                    self.exception_handler(msg, partial(self.load_data, filename,
                                                        template=template),
                                           'data_res', 'File Conflict', delay=True,
                                           disabled=['load'] if template else [])
                return True
            if overwrite != 'merge' and overwrite != 'overwrite' and not template:
                self.delete_all_buttons(notify=False)
            for header in headers:
                self.add_button(header[1])
            if overwrite != 'merge' and not template:
                self.data_filename = filename
            self.set_tittle()
            self.notify_chan_update(score_type='xyt')
            self.update_line()
            self.update_t_states()
            self.update_plot()
        else:
            self.exception_handler("You haven't opened a video file yet.", None,
                                   'error', 'Error!')
            return True
        return True

    def get_next_frame(self, *args):
        t_start = time.clock()
        try:
            curr_score = self.curr_score
            touch = self.touch or self.released_touch
            self.released_touch = None
            if touch and curr_score and curr_score.settings['score_type'].startswith('xy'):
                self.update_plot(btn=curr_score, pts=self.last_pts, new_val=touch)
            frame = self.next_frame
            self.img_w.set_texture(frame[0])
            self.last_frame = frame
            previous_pts = self.last_pts
            self.last_pts = frame[3]
            self.next_frame = self.media.get_next_frame()
            if self.limit_range and frame[3] > self.end_time:
                raise EOFError()
        except EOFError:
            self.pause()
            self.seek_to_pts(self.start_time if self.limit_range else 0., display_next=False)
            #self.reload_displayed_cols()
            return
        if self.seeked:
            self.notify_chan_update(score_type='xyt')
            self.seek_t_states(previous_pts, self.last_pts)
            self.seeked = False
        self.update_line(chan=-1, score_type='xyt')
        self.update_line(chan=-1, score_type='t')
        self.update_t_states()
        self.seek_slider_w.value = self.last_pts
        if self.frame_rate and self.pause_btn_w.state != 'down':
            t= max(0.0, (self.next_frame[3] - frame[3])/self.frame_rate - (time.clock() - t_start))
            Clock.schedule_once(self.get_next_frame, t)

    def seek_to_pts(self, pts=None, relative=None, display_next=True):
        if self.started:
            Clock.unschedule(self.get_next_frame)
            if relative:
                pts = self.last_pts + relative * self.seeking_dist
            self.media.seek_to_pts(pts)
            self.seeked = True
            while 1:
                try:
                    self.next_frame = self.media.get_next_frame()
                    break
                except EOFError:
                    pass
            if display_next:
                Clock.schedule_once(self.get_next_frame)

    def seek_to_next_break(self):
        btn = self.curr_score
        if not btn:
            return
        col = self.score_dict_inv[btn]
        if self.media and btn and col[1].endswith('t'):
            pts = self.media.next_chan_break(col[0], self.last_pts)
            if pts:
                self.seek_to_pts(pts)

    def pause(self, virtual=True):
        if virtual:
            self.pause_btn_w.state= 'down'
        Clock.unschedule(self.get_next_frame)
        return True

    def unpause(self, virtual=True):
        if virtual:
            self.pause_btn_w.state= 'normal'
        if self.frame_rate and self.started:
            Clock.schedule_once(self.get_next_frame, 0.033)
        self.touch= None

    def last_buffer(self):
        return self.last_frame[0]

    def update_data(self, purpose):
        if self.media:
            if purpose == 'discard':
                self.load_data(self.data_filename, 'load')
            else:
                try:
                    self.media.modify_log(purpose)
                except Exception as e:
                    self.exception_handler(str(e), None, 'error', 'Error!')

    def close_video(self):
        if self.export_file:
            self.export_file.close()
            self.export_file = None
        if self.media:
            Clock.unschedule(self.get_next_frame)
            Clock.unschedule(self.media.modify_log)
            self.media.close()
        self.initialize()
        if self.export_btns_w:
            self.export_btns_w.clear_widgets()
            self.curr_export_btn = None


    def add_button(self, kargs, notify_media=False):
        count = self.score_count
        color = [1] * 4
        path_fwd_tint = self.path_fwd_tint
        score_type = kargs['score_type']
        if 'draw' in kargs:
            kargs['draw'] = False

        if score_type == 'xyt':
            bar = self.xyt_buttons_w
            btn = PathButton()
            btn.display.update({'e':None, 'f_s':None})
            plot_widget = self.xyt_plot_w
        elif score_type == 'xy':
            bar = self.xy_buttons_w
            btn = PathButton()
        elif score_type == 't':
            bar = self.t_buttons_w
            btn = PathButton()
            plot_widget = self.t_plot_w
        settings = btn.settings
        settings.update(tracker.TrackLog.get_default_settings(score_type))
        settings.update(kargs)
        btn.down_color = color[:]
        comp = list(colorsys.rgb_to_hsv(*color[0:3]))
        comp[0] += 0.5
        if comp[0] > 1:
            comp[0] -= 1
        comp = list(colorsys.hsv_to_rgb(*comp))
        if color[0:3] == [1, 1, 1]:
            comp = [0, 0, 0]
        elif color[0:3] == [0, 0, 0]:
            comp = [1, 1, 1]
        btn.comp_color[0:3] = comp
        if score_type.startswith('xy'):
            with self.img_scatter_w.canvas:
                btn.line_fwd_color = Color(color[0]*path_fwd_tint, color[1]*path_fwd_tint,
                                          color[2]*path_fwd_tint, group=str('path%d' % count))
                btn.fwd_line = Line(group=str('path%d' % count))
                btn.line_color = Color(color[0], color[1], color[2], group=str('path%d' % count))
                btn.line = Line(group=str('path%d' % count), close=score_type=='xy')
        if score_type.endswith('t'):
            comp_color = btn.comp_color[0:3]
            with plot_widget.canvas:
                btn.plot_group_ctx = InstructionGroup(group=str('path%d' % count))
                btn.plot_comp_group_ctx = InstructionGroup(group=str('path%d' % count))
                btn.plot_mix_group_ctx = InstructionGroup(group=str('path%d' % count))
            btn.plot_color = Color(*color[0:3])
            btn.plot_group_ctx.add(btn.plot_color)
            btn.plot_comp_color = Color(*comp_color[0:3], group=str('path%d' % count))
            btn.plot_comp_group_ctx.add(btn.plot_comp_color)
            btn.plot_mix_color = Color(*comp_color[0:3], group=str('path%d' % count))
            btn.plot_mix_color.a = 0.5
            btn.plot_mix_group_ctx.add(btn.plot_mix_color)
            btn.quad_list = []
            btn.quad_comp_list = []
            btn.quad_mix_list = []
            btn.plot_list = []
            btn.plot_count = -1
            if settings['plot']:
                h = self.plot_pixel_height
                dist = 0
                for bttn in bar.children[1:]:
                    if not bttn.settings['plot']:
                        continue
                    bttn.plot_count += 1
                    dist = max(dist, bttn.plot_count)
                    for quad_list in (bttn.quad_list, bttn.quad_comp_list, bttn.quad_mix_list):
                        for quad in quad_list:
                            points = quad.points
                            for i in range(len(points)/2):
                                points[i*2 + 1] += h
                            quad.points = points
                plot_widget.height = (1+dist)*h
                btn.plot_count = 0
        if score_type == 't':
            group = settings['group']
            if group:
                groups = self.t_btn_groups
                if group in groups:
                    groups[group].append(btn)
                else:
                    groups[group] = [btn]
            self.t_btn_groups_inv[btn] = group

        bar.add_widget(btn, 1)
        self.score_dict[count]= (bar, btn, score_type)
        self.score_dict_inv[btn]= (count, score_type)
        self.score_count = count + 1
        if notify_media and self.media:
            self.media.add_header(count, settings)
        self.update_plot(btn=btn)
        label_name = settings['name']
        if 'keycode' in settings and settings['keycode']:
            label_name += ' ('+settings['keycode']+')'
        if 'event_type' in settings:
            label_name += self.t_type_subscript[settings['event_type']]
        btn.score_btn.text = label_name
        if notify_media:

            self.curr_edit_score = btn
            self.edit_screen_w.current = score_type
            self.edit_screen_w.get_screen(score_type).settings.set_settings(settings)
            self.color_selector.open()
        else:
            self.curr_edit_score = btn
            self.edit_button(settings, False)

    def edit_button(self, kargs, notify_media=True):
        btn = self.curr_edit_score
        col = self.score_dict_inv[btn]
        btn.state = 'normal'
        settings = btn.settings
        if 'keycode' in kargs and kargs['keycode'] and kargs['keycode'] in self.keycode_dict:
            kargs['keycode'] = ''
        if self.media and notify_media:
            self.media.edit_header(col[0], kargs)
        fwd_tint = self.path_fwd_tint
        color = kargs['color']
        btn.down_color = color[:]
        comp = list(colorsys.rgb_to_hsv(*color[0:3]))
        comp[0] += 0.5
        if comp[0] > 1:
            comp[0] -= 1
        comp = list(colorsys.hsv_to_rgb(*comp))
        if color[0:3] == [1, 1, 1]:
            comp = [0, 0, 0]
        elif color[0:3] == [0, 0, 0]:
            comp = [1, 1, 1]
        btn.comp_color[0:3] = comp
        label_name = kargs['name']
        if 'keycode' in kargs and kargs['keycode']:
            label_name += ' ('+kargs['keycode']+')'
        if 'event_type' in kargs:
            label_name += self.t_type_subscript[kargs['event_type']]
        btn.score_btn.text = label_name
        if col[1].startswith('xy'):
            btn.line_color.rgba = color[:]
            btn.line_fwd_color.rgba = [c * fwd_tint for c in color[0:3]] + [1]
        if col[1].endswith('t'):
            btn.plot_color.rgb = color[0:3]
            btn.plot_comp_color.rgb = btn.comp_color[0:3]
            btn.plot_mix_color.rgb = btn.comp_color[0:3]
            btn.plot_mix_color.a = 0.5
            if kargs['plot'] != settings['plot']:
                plot_widget = self.t_plot_w if col[1] == 't' else self.xyt_plot_w
                if not kargs['plot']:
                    h = self.plot_pixel_height
                    dist = btn.plot_count - 1
                    for bttn in btn.parent.children[btn.parent.children.index(btn)+1:]:
                        if not bttn.settings['plot']:
                            continue
                        bttn.plot_count -= 1
                        dist = max(dist, bttn.plot_count)
                        for quad_list in (bttn.quad_list, bttn.quad_comp_list, bttn.quad_mix_list):
                            for quad in quad_list:
                                points = quad.points
                                for i in range(len(points)/2):
                                    points[i*2 + 1] -= h
                                quad.points = points
                    plot_widget.height = (1+dist)*h
                    for quad_list, quad_ctx in ((btn.quad_list, btn.plot_group_ctx),
                                                (btn.quad_comp_list, btn.plot_comp_group_ctx),
                                                (btn.quad_mix_list, btn.plot_mix_group_ctx)):
                        for quad in quad_list:
                            quad_ctx.remove(quad)
                        del quad_list[:]
                    btn.plot_list = []
                    btn.plot_count = -1
                else:
                    children = btn.parent.children
                    idx = children.index(btn)
                    plot_count = 0
                    for bttn in children[1:idx]:
                        if bttn.settings['plot']:
                            plot_count += 1
                    btn.plot_count = plot_count
                    h = self.plot_pixel_height
                    dist = plot_count
                    for bttn in children[idx+1:]:
                        if not bttn.settings['plot']:
                            continue
                        bttn.plot_count += 1
                        dist = max(dist, bttn.plot_count)
                        for quad_list in (bttn.quad_list, bttn.quad_comp_list, bttn.quad_mix_list):
                            for quad in quad_list:
                                points = quad.points
                                for i in range(len(points)/2):
                                    points[i*2 + 1] += h
                                quad.points = points
                    plot_widget.height = (1+dist)*h
        if col[1] == 't':
            keycode = kargs['keycode']
            if btn in self.keycode_dict_inv:    # already has key
                if keycode:                     # we again assign key
                    if keycode != self.keycode_dict_inv[btn]:   # and they are different
                        del self.keycode_dict[settings['keycode']]
                        self.keycode_dict[keycode] = btn, 'off'
                        self.keycode_dict_inv[btn] = keycode
                else:                           # we cleared the key
                    keycode = self.keycode_dict_inv[btn]
                    del self.keycode_dict_inv[btn]
                    del self.keycode_dict[keycode]
            else:                               # didn't have key
                if keycode:                     # we assign key
                    self.keycode_dict[keycode] = btn, 'off'
                    self.keycode_dict_inv[btn] = keycode
            groups_inv = self.t_btn_groups_inv
            if 'group' in kargs and groups_inv[btn] != kargs['group']:
                groups = self.t_btn_groups
                group = groups_inv[btn]
                if group:
                    group_list = groups[group]
                    del group_list[group_list.index(btn)]
                    if not len(group_list):
                        del groups[group]
                group = kargs['group']
                if group:
                    if group in groups:
                        groups[group].append(btn)
                    else:
                        groups[group] = [btn]
                groups_inv[btn] = group
        if col[1].endswith('t'):
            old_plot = settings['plot']
        settings.update(kargs)
        if col[1].endswith('t') and kargs['plot'] != old_plot and kargs['plot']:
            self.update_plot(btn=btn)

    def clear_btn(self, btn):
        if self.media:
            self.media.clear_header(self.score_dict_inv[btn][0])
            self.update_line(btn=btn)
            self.update_plot(btn=btn)

    def delete_button(self, btn, notify=True):
        score_dict_inv = self.score_dict_inv
        col = score_dict_inv[btn]
        self.img_scatter_w.canvas.remove_group(str('path%d' % col[0]))
        if col[1] == 'xyt':
            bar = self.xyt_buttons_w
        elif col[1] == 'xy':
            bar = self.xy_buttons_w
        elif col[1] == 't':
            bar = self.t_buttons_w
            keycode_dict_inv = self.keycode_dict_inv
            if btn in keycode_dict_inv:
                keycode = keycode_dict_inv[btn]
                del keycode_dict_inv[btn]
                del self.keycode_dict[keycode]
            if btn.settings['group']:
                groups = self.t_btn_groups
                group = btn.settings['group']
                group_list = groups[group]
                del group_list[group_list.index(btn)]
                if not len(group_list):
                    del groups[group]
            del self.t_btn_groups_inv[btn]
        if col[1].endswith('t'):
            plot_widget = self.t_plot_w if col[1] == 't' else self.xyt_plot_w
            for quad_ctx, quad_list in ((btn.plot_group_ctx, btn.quad_list),
                                            (btn.plot_comp_group_ctx, btn.quad_comp_list),
                                            (btn.plot_mix_group_ctx, btn.quad_mix_list)):
                for quad in quad_list:
                    quad_ctx.remove(quad)
            plot_widget.canvas.remove_group(str('path%d' % col[0]))
            if btn.settings['plot']:
                h = self.plot_pixel_height
                dist = btn.plot_count - 1
                for bttn in btn.parent.children[btn.parent.children.index(btn)+1:]:
                    if not bttn.settings['plot']:
                        continue
                    bttn.plot_count -= 1
                    dist = max(dist, bttn.plot_count)
                    for quad_list in (bttn.quad_list, bttn.quad_comp_list, bttn.quad_mix_list):
                        for quad in quad_list:
                            points = quad.points
                            for i in range(len(points)/2):
                                points[i*2 + 1] -= h
                            quad.points = points
                plot_widget.height = (1+dist)*h
        bar.remove_widget(btn)
        if notify and self.media:
            self.media.delete_header(col[0])
        self.score_count -= 1
        for bttn, chann in score_dict_inv.iteritems():
            if chann[0] > col[0]:
                score_dict_inv[bttn] = (chann[0] - 1, chann[1])
        del score_dict_inv[btn]
        score_dict = self.score_dict
        for i in range(col[0], len(score_dict)-1):
            score_dict[i] = score_dict[i+1]
        del score_dict[len(score_dict)-1]
        if self.curr_score == btn:
            self.curr_score = None
            self.xy_state = None

    def delete_all_buttons(self, notify=True):
        for btn in self.score_dict_inv.keys():
            if btn:
                self.delete_button(btn, notify=notify)
        self.curr_edit_score = None
        self.curr_score = None
        self.xy_state = None

    def get_all_buttons(self):
        return [(col[0], btn.settings) for btn, col in self.score_dict_inv.iteritems() if btn]


    def score_button_press(self, btn, press, virtual=False, release_groups=True):
        mode = self.mode
        chan, score_type = self.score_dict_inv[btn]
        settings = btn.settings
        if (not mode) or virtual:
            if score_type.startswith('xy'):
                if press != 'release':
                    return
                if btn.score_btn.state == 'down':
                    settings['draw'] = True
                    if self.media:
                        self.update_line(btn=btn)
                else:
                    self.hide_score(btn, chan)
            else:
                event_type = settings['event_type']
                if event_type == 'event':
                    if ((not self.media) or (press == 'release' and (btn.key_touching or btn.touching))):
                        return
                    last_state = self.media.get_data_point(chan, self.last_pts)
                    if press != 'release':
                        btn.score_btn.state = 'down' if last_state else 'normal'
                        return
                    self.update_plot(chan=chan, pts=self.last_pts, new_val=not last_state)
                    btn.score_btn.state = 'normal' if last_state else 'down'
                    if release_groups:
                        self.release_groups(btn, settings['group'])
                elif event_type == 'press':
                    if press == 'press' or press == 'hold':
                        if btn.score_btn.state == 'normal':
                            btn.score_btn.state = 'down'
                        if self.media:
                            self.update_plot(chan=chan, pts=self.last_pts, new_val=True)
                            if release_groups:
                                self.release_groups(btn, settings['group'])
                    elif press == 'release':
                        if self.media and not(btn.key_touching or btn.touching):
                            last_state = self.media.get_data_point(chan, self.last_pts)
                            if last_state:
                                self.update_plot(chan=chan, pts=self.last_pts, new_val=False)
                            btn.score_btn.state = 'normal'
                elif event_type == 'toggle':
                    if press == 'press':
                        last_state = self.media and self.media.get_data_point(chan, self.last_pts)
                        btn.score_btn.state = 'down' if last_state else 'normal'
                    elif press == 'release':
                        last_state = self.media and self.media.get_data_point(chan, self.last_pts)
                        if (not release_groups) or ((btn.toggled or last_state) and not (btn.key_touching or btn.touching)):
                            btn.toggled = False
                            btn.score_btn.state = 'normal'
                            if self.media:
                                self.update_plot(chan=chan, pts=self.last_pts, new_val=False)
                        elif (not btn.toggled) and not (btn.key_touching or btn.touching):
                            btn.toggled = True
                            btn.score_btn.state = 'down'
                            if self.media:
                                self.update_plot(chan=chan, pts=self.last_pts, new_val=True)
                                if release_groups:
                                    self.release_groups(btn, settings['group'])
                    elif press == 'hold':
                        if self.media and btn.toggled:
                            last_point = self.media.get_data_point(chan, self.last_pts)
                            if not last_point:
                                self.update_plot(chan=chan, pts=self.last_pts, new_val=True)
                                if release_groups:
                                    self.release_groups(btn, settings['group'])
            return

        if press == 'press':
            return
        if btn.score_btn.state == 'down':
            btn.score_btn.state = 'normal'
        else:
            btn.score_btn.state = 'down'
        if mode == 'edit':
            self.curr_edit_score = btn
            self.edit_screen_w.current = score_type
            self.edit_screen_w.get_screen(score_type).settings.set_settings(settings)
            self.color_selector.open()
        elif mode == 'clear':
            self.clear_btn(btn)
        elif mode == 'delete':
            self.delete_button(btn)
        elif mode == 'activate':
            if self.curr_score == btn:
                self.curr_score = None
                self.xy_state = None
            else:
                if self.media:
                    if btn.settings['score_type'].startswith('xy'):
                        if btn.score_btn.state == 'normal':
                            settings['draw'] = True
                            self.update_line(btn=btn)
                            btn.score_btn.state = 'down'
                        self.xy_state = btn if score_type == 'xy' else None
                    self.curr_score = btn

        self.seek_bar_w.delete_btn.state = 'normal'
        self.seek_bar_w.clear_btn.state = 'normal'
        self.seek_bar_w.activate_btn.state = 'normal'
        self.seek_bar_w.edit_btn.state = 'normal'
        self.mode = ''

    def hide_score(self, btn, chan):
        score_type = btn.settings['score_type']
        if score_type.startswith('xy'):
            btn.settings['draw'] = False
            if self.curr_score == btn:
                self.curr_score = None
                self.xy_state = None
            self.notify_chan_update(chan, score_type)

    def notify_chan_update(self, chan=-1, score_type=''):
        ''' If chan is -1 and score_type is '', then the plot will also be updated.
        '''
        if chan != -1:
            btn = self.score_dict[chan];
            if btn[2] == 'xyt':
                btn[1].display['e'] = None
                btn[1].display['f_s'] = None
                self.update_line(chan=chan)
                if not score_type:
                    self.update_plot(chan=chan)
            elif btn[2] == 'xy':
                self.update_line(chan=chan)
            elif btn[2] == 't':
                self.update_t_states(btn[1])
                if not score_type:
                    self.update_plot(chan=chan)
        else:
            for chan, btn in self.score_dict.items():
                if (not score_type) or score_type == btn[2]:
                    self.notify_chan_update(chan, btn[2])

    def update_line(self, chan=-1, btn=None, score_type=''):
        if chan == -1 and btn is None:
            for btn, chan in self.score_dict_inv.iteritems():
                if (not score_type) or score_type == chan[1]:
                    self.update_line(chan=chan[0])
        else:
            if chan != -1:
                btn = self.score_dict[chan]
                score_type = btn[2]
                btn = btn[1]
            else:
                chan = self.score_dict_inv[btn]
                score_type = chan[1]
                chan = chan[0]
            if score_type == 'xyt':
                if btn.settings['draw'] and self.media:
                    btn.display['e'] = self.media.get_xyt_state(chan, self.last_pts, self.xyt_fwd_dur,
                                                                btn.display['e'], btn.fwd_line.points)
                    btn.display['f_s'] = self.media.get_xyt_state(chan, self.last_pts, self.xyt_bkwd_dur,
                                                                btn.display['f_s'], btn.line.points)
                    btn.line.points = btn.line.points
                    btn.fwd_line.points = btn.fwd_line.points
                else:
                    btn.line.points[:] = []
                    btn.fwd_line.points[:] = []
                    btn.line.points = btn.line.points
                    btn.fwd_line.points = btn.fwd_line.points
            elif score_type == 'xy':
                if btn.settings['draw'] and self.media:
                    self.media.get_xy_state(chan, btn.line.points)
                    btn.line.points = btn.line.points
                else:
                    btn.line.points[:] = []
                    btn.line.points = btn.line.points
            elif score_type == 't':
                pass

    def update_plot(self, chan=-1, btn=None, score_type='', pts=None, new_val=None, pixel=None):
        if not self.media:
            return
        if chan == -1 and btn is None:
            if pts is None and pixel is None:
                width = int(self.t_plot_w.width/float(self.plot_pixel_width))
                self.plot_pts_breaks = [1, ] * width
                self.plot_pts_dups = [0, ] * width
                self.plot_pts_list = [[] for i in range(width)]
                plot_pts_list = self.plot_pts_list
                plot_pts_breaks = self.plot_pts_breaks
                plot_pts_dups = self.plot_pts_dups
                ratio = width/float(self.duration)
                s = 0
                for bttn in self.t_buttons_w.children[1:]:
                    if bttn.settings['plot']:
                        s += 1
                self.t_plot_w.height = s * self.plot_pixel_height
                s = 0
                for bttn in self.xyt_buttons_w.children[1:]:
                    if bttn.settings['plot']:
                        s += 1
                self.xyt_plot_w.height = s * self.plot_pixel_height
                for group in self.media.get_pts_lists():
                    for pts in group:
                        plot_pts_list[int(floor(pts*ratio))].append(pts)
                    for i in range(int(floor(group[-1]*ratio))-1, int(floor(group[0]*ratio)), -1):
                        plot_pts_breaks[i] = 0
                        if not plot_pts_list[i]:
                            plot_pts_list[i].append(plot_pts_list[i+1][0])
                            plot_pts_dups[i] = 1
                if self.pts_complete:
                    plot_pts_breaks[0] = 0
                    plot_pts_breaks[-1] = 0
                for btn in self.score_dict_inv:
                    if ((not score_type) or score_type == btn.settings['score_type']):
                        self.update_plot(btn=btn)
            else:
                for btn in self.score_dict_inv:
                    if ((not score_type) or score_type == btn.settings['score_type']):
                        self.update_plot(btn=btn, pts=pts, pixel=pixel)
        else:
            if chan != -1:
                btn = self.score_dict[chan]
                score_type = btn[2]
                btn = btn[1]
            else:
                chan = self.score_dict_inv[btn]
                score_type = chan[1]
                chan = chan[0]
            if (not 'plot' in btn.settings) or not btn.settings['plot']:
                return
            plot_pts_breaks = self.plot_pts_breaks
            plot_pts_dups = self.plot_pts_dups
            plot_pts_list = self.plot_pts_list
            if pts is not None or pixel is not None:
                plot_list = btn.plot_list
                width = self.plot_pixel_width
                height = self.plot_pixel_height
                y_low = btn.plot_count * height
                y_high = y_low + (height-2)
                if pts is not None:
                    pixel = int(floor(pts*self.t_plot_w.width/float(self.plot_pixel_width*self.duration)))
                    last = not self.media.is_data_default(chan, pts)
                    self.media.add_data_point(chan, new_val, pts)
                    new_val = not self.media.is_data_default(chan, pts)
                    pixel_dup = pixel - 1
                    if last != new_val:
                        while pixel_dup > 0 and plot_pts_dups[pixel_dup] and pts == plot_pts_list[pixel_dup][0]:
                            if new_val:
                                plot_list[pixel_dup][0] = 1
                                plot_list[pixel_dup][1] = 0
                            else:
                                plot_list[pixel_dup][0] = 0
                                plot_list[pixel_dup][1] = 1
                            self.update_plot(btn=btn, pixel=pixel_dup)
                            pixel_dup -= 1
                        if new_val:
                            plot_list[pixel][0] += 1
                            plot_list[pixel][1] -= 1
                        else:
                            plot_list[pixel][0] -= 1
                            plot_list[pixel][1] += 1
                normm = plot_list[pixel][0] and plot_list[pixel][2] == -1
                normmi = (not plot_list[pixel][0]) and plot_list[pixel][2] != -1
                comp = (not plot_list[pixel][0]) and (plot_list[pixel][1] or plot_pts_breaks[pixel]) and plot_list[pixel][3] == -1
                compi = (plot_list[pixel][0] or (not (plot_list[pixel][1] or plot_pts_breaks[pixel]))) and plot_list[pixel][3] != -1
                mix = plot_list[pixel][0] and (plot_list[pixel][1] or plot_pts_breaks[pixel]) and plot_list[pixel][4] == -1
                mixi = ((not plot_list[pixel][0]) or (not (plot_list[pixel][1] or plot_pts_breaks[pixel]))) and plot_list[pixel][4] != -1
                colors = ((normm, normmi, 2, btn.plot_group_ctx, btn.quad_list),)
                if self.plot_use_contrast:
                    colors += ((comp, compi, 3, btn.plot_comp_group_ctx, btn.quad_comp_list),
                               (mix, mixi, 4, btn.plot_mix_group_ctx, btn.quad_mix_list))
                for state, statei, idx, ctx, quads in colors:
                    if state:
                        if pixel + 1 < len(plot_list) and plot_list[pixel+1][idx] != -1:
                            plot_list[pixel][idx] = plot_list[pixel+1][idx]
                            points = quads[plot_list[pixel][idx]].points
                            points[0] -= width
                            points[2] -= width
                            quads[plot_list[pixel][idx]].points = points
                        elif pixel and plot_list[pixel-1][idx] != -1:
                            plot_list[pixel][idx] = plot_list[pixel-1][idx]
                            points = quads[plot_list[pixel][idx]].points
                            points[4] += width
                            points[6] += width
                            quads[plot_list[pixel][idx]].points = points
                        else:
                            plot_list[pixel][idx] = len(quads)
                            quad = Quad()
                            ctx.add(quad)
                            quads.append(quad)
                            points = [y_low, ] * 8
                            points[0] = points[2] = pixel*width
                            points[4] = points[6] = (pixel+1)*width
                            points[3] = points[5] = y_high
                            quad.points = points
                    elif statei:
                        if (pixel + 1 < len(plot_list) and plot_list[pixel+1][idx] != -1
                            and ((not pixel) or plot_list[pixel-1][idx] == -1)):
                            points = quads[plot_list[pixel][idx]].points
                            points[0] += width
                            points[2] += width
                            quads[plot_list[pixel][idx]].points = points
                            plot_list[pixel][idx] = -1
                        elif (pixel and plot_list[pixel-1][idx] != -1
                              and (pixel + 1 == len(plot_list) or plot_list[pixel+1][idx] == -1)):
                            points = quads[plot_list[pixel][idx]].points
                            points[4] -= width
                            points[6] -= width
                            quads[plot_list[pixel][idx]].points = points
                            plot_list[pixel][idx] = -1
                        elif ((pixel + 1 < len(plot_list) and plot_list[pixel+1][idx] == -1) or
                              (pixel and plot_list[pixel-1][idx] == -1)):
                            quads[plot_list[pixel][idx]].points = [0, ] * 8
                            plot_list[pixel][idx] = -1
                        else:
                            quad_old = quads[plot_list[pixel][idx]]
                            pos = len(quads)
                            quad = Quad()
                            ctx.add(quad)
                            quads.append(quad)
                            points_old = quad_old.points
                            points = points_old[:]
                            points[4] = points[6] = pixel*width
                            quad.points = points
                            points_old[0] = points_old[2] = (pixel+1)*width
                            quad_old.points = points_old
                            old_idx = plot_list[pixel][idx]
                            plot_list[pixel][idx] = -1
                            i = pixel - 1
                            while i >= 0 and plot_list[i][idx] == old_idx:
                                plot_list[i][idx] = pos
                                i -= 1
            else:
                pts_list = self.plot_pts_list
                btn.plot_list = [[0,0,-1,-1,-1] for i in range(len(pts_list))]
                plot_list = btn.plot_list
                pixel_height = self.plot_pixel_height
                pixel_width = self.plot_pixel_width
                y_low = btn.plot_count * pixel_height
                y_high = y_low + (pixel_height-2)
                for i in range(len(pts_list)):
                    for pts in pts_list[i]:
                        if self.media.is_data_default(chan, pts):
                            plot_list[i][1] += 1
                        else:
                            plot_list[i][0] += 1
                count_t = -1    # true
                count_f = -1    # comp
                count_m = -1    # mix
                if plot_list[0][0]:
                    plot_list[0][2] = 0
                    count_t = 0
                if plot_pts_breaks[0] or plot_list[0][1]:
                    if plot_list[0][0]:
                        plot_list[0][4] = 0
                        count_m = 0
                    else:
                        plot_list[0][3] = 0
                        count_f = 0
                for i in range(1, len(pts_list)):
                    if plot_list[i][0]:
                        if not plot_list[i-1][0]:
                            count_t += 1
                        plot_list[i][2] = count_t
                    if plot_pts_breaks[i] or plot_list[i][1]:
                        if plot_list[i][0]:
                            if plot_list[i-1][4] == -1:
                                count_m += 1
                            plot_list[i][4] = count_m
                        else:
                            if plot_list[i-1][3] == -1:
                                count_f += 1
                            plot_list[i][3] = count_f
                count_t += 1
                count_f += 1
                count_m += 1
                quads = ((2, count_t, btn.plot_group_ctx, btn.quad_list),)
                if self.plot_use_contrast:
                    quads += ((3, count_f, btn.plot_comp_group_ctx, btn.quad_comp_list),
                              (4, count_m, btn.plot_mix_group_ctx, btn.quad_mix_list))
                else:
                    for quad_ctx, quad_list in ((btn.plot_comp_group_ctx, btn.quad_comp_list),
                                                (btn.plot_mix_group_ctx, btn.quad_mix_list)):
                        for quad in quad_list:
                            quad_ctx.remove(quad)
                        del quad_list[:]
                for idx, count, quad_ctx, quad_list in quads:
                    for quad in quad_list[count:]:
                        quad_ctx.remove(quad)
                    del quad_list[count:]
                    for i in range(len(quad_list), count):
                        quad = Quad()
                        quad_ctx.add(quad)
                        quad_list.append(quad)
                    #start = -1
                    count = 0
                    if plot_list[0][idx] != -1:
                        start = 0
                    for i in range(0, len(pts_list)):
                        if plot_list[i][idx] != -1 and (i == len(pts_list)-1 or plot_list[i+1][idx] == -1):
                            points = [y_low, ] * 8
                            points[0] = points[2] = start*pixel_width
                            points[4] = points[6] = (i+1)*pixel_width
                            points[3] = points[5] = y_high
                            quad_list[count].points = points
                            count += 1
                        if plot_list[i][idx] == -1 and i < len(pts_list)-1 and plot_list[i+1][idx] != -1:
                            start = i+1

    def edit_plot_breaks(self, pts_list=None, pts_new=None):
        plot_pts_breaks = self.plot_pts_breaks
        if pts_list is None and self.pts_complete:
            temp = plot_pts_breaks[0]
            plot_pts_breaks[0] = 0
            if temp:
                self.update_plot(pixel=0)
            temp = plot_pts_breaks[-1]
            plot_pts_breaks[-1] = 0
            if temp:
                self.update_plot(pixel=len(plot_pts_breaks)-1)
        elif pts_list is None:
            raise Exception('You cannot have a pixel list smaller that 1.')
        elif pts_new is None:
            plot_pts_list = self.plot_pts_list
            plot_pts_dups = self.plot_pts_dups
            ratio = self.t_plot_w.width/float(self.plot_pixel_width*self.duration)
            for i in range(int(floor(pts_list[-1]*ratio))-1, int(floor(pts_list[0]*ratio)), -1):
                temp = plot_pts_breaks[i]
                plot_pts_breaks[i] = 0
                if not plot_pts_list[i]:
                    plot_pts_list[i].append(plot_pts_list[i+1][0])
                    plot_pts_dups[i] = 1
                    for bttn, chann in self.score_dict_inv.iteritems():
                        if 'plot' in bttn.settings and bttn.settings['plot']:
                            if self.media.is_data_default(chann[0], plot_pts_list[i][0]):
                                bttn.plot_list[i][1] += 1
                            else:
                                bttn.plot_list[i][0] += 1
                if temp:
                    self.update_plot(pixel=i)
        else:
            if pts_new > self.duration:
                self.duration = pts_new
                self.seek_slider_w.range = (0, self.duration)
                self.update_plot()
                return
            plot_pts_list = self.plot_pts_list
            plot_pts_dups = self.plot_pts_dups
            ratio = self.t_plot_w.width/float(self.plot_pixel_width*self.duration)
            pixel = int(floor(pts_new*ratio))
            pixel_low = int(floor(pts_list[0]*ratio))
            bisect.insort(plot_pts_list[pixel], pts_new)
            if pts_new == plot_pts_list[pixel][0]:
                update = []
                for i in range(pixel-1, pixel_low, -1):
                    if plot_pts_dups[i] and plot_pts_list[i] and plot_pts_list[i][0] != pts_new:
                        update.append(i)
                    else:
                        break
                for i in reversed(update):
                    plot_pts_list[i][0] = pts_new
                    for bttn, chann in self.score_dict_inv.iteritems():
                        if 'plot' in bttn.settings and bttn.settings['plot']:
                            if self.media.is_data_default(chann[0], pts_new):
                                bttn.plot_list[i][1] = 1
                                bttn.plot_list[i][0] = 0
                            else:
                                bttn.plot_list[i][0] = 1
                                bttn.plot_list[i][1] = 0
                    self.update_plot(pixel=i)
            for bttn, chann in self.score_dict_inv.iteritems():
                if 'plot' in bttn.settings and bttn.settings['plot']:
                    if self.media.is_data_default(chann[0], pts_new):
                        bttn.plot_list[pixel][1] += 1
                    else:
                        bttn.plot_list[pixel][0] += 1
            self.update_plot(pixel=pixel)
            for i in range(pixel-1, pixel_low, -1):
                temp = plot_pts_breaks[i]
                plot_pts_breaks[i] = 0
                if not plot_pts_list[i]:
                    temp = 1
                    plot_pts_list[i].append(plot_pts_list[i+1][0])
                    plot_pts_dups[i] = 1
                    for bttn, chann in self.score_dict_inv.iteritems():
                        if 'plot' in bttn.settings and bttn.settings['plot']:
                            if self.media.is_data_default(chann[0], plot_pts_list[i][0]):
                                bttn.plot_list[i][1] += 1
                            else:
                                bttn.plot_list[i][0] += 1

                if temp:
                    self.update_plot(pixel=i)
                else:
                    break

    def update_t_states(self, btn=None):
        if not self.media:
            return
        if btn is not None:
            chan_list = [(btn, self.score_dict_inv[btn])]
        else:
            chan_list = self.score_dict_inv.iteritems()
        curr_score = self.curr_score
        for btn, chan in chan_list:
            if chan[1] != 't':
                continue
            if self.cut_t_button_w.state == 'down' and btn == curr_score:
                self.update_plot(chan=chan[0], pts=self.last_pts, new_val=False)
            settings = btn.settings
            if settings['event_type'] == 'event':
                last_point = self.media.get_data_point(chan[0], self.last_pts)
                if last_point != (btn.score_btn.state == 'down'):
                    btn.score_btn.state = 'down' if last_point else 'normal'
            elif settings['event_type'] == 'press':
                if btn.touching or btn.key_touching:
                    self.score_button_press(btn, 'hold', virtual=True)
                if self.media:
                    last_point = self.media.get_data_point(chan[0], self.last_pts)
                    if last_point != (btn.score_btn.state == 'down'):
                        btn.score_btn.state = 'down' if last_point else 'normal'
            elif settings['event_type'] == 'toggle':
                if btn.toggled:
                    self.score_button_press(btn, 'hold', virtual=True)
                if self.media:
                    last_point = self.media.get_data_point(chan[0], self.last_pts)
                    if last_point != (btn.score_btn.state == 'down'):
                        btn.score_btn.state = 'down' if last_point else 'normal'

    def release_groups(self, btn, group):
        groups = self.t_btn_groups
        if group and group in groups:
            group_list = groups[group]
            score_dict_inv = self.score_dict_inv
            for bttn in group_list:
                if bttn != btn:
                    if bttn.score_btn.state == 'down' or self.media.get_data_point(score_dict_inv[bttn][0], self.last_pts):
                        self.score_button_press(bttn, 'release', virtual=True, release_groups=False)

    def seek_t_states(self, start_pts, end_pts):
        if self.media:
            for btn, chan in self.score_dict_inv.iteritems():
                if btn.settings['score_type'] == 't' and btn.settings['event_type'] == 'toggle' and btn.toggled:
                    self.media.add_data_range(chan[0], True, start_pts, end_pts)
                    self.update_plot(btn=btn)


    def load_exporter(self, filename, overwrite='raise'):
        if self.data_filename:
            if overwrite == 're-save':
                overwrite = 'overwrite'
                filename = self.export_filename
            if not filename.endswith('.txt'):
                filename += '.txt'
            filename = os.path.normpath(filename)
            try:
                if filename == '.txt':
                    raise Exception('You have not provided a export file.')
                exists = os.path.exists(filename)
                old_file = self.export_file
                new_btns = ''
                if overwrite == 'overwrite' or not exists:
                    if old_file:
                        old_file.close()
                    export_file = open(filename, 'w+')
                    self.export_file = export_file
                    for chan in reversed(self.export_btns_w.children):
                        export_file.write('channel:'+chan.text+'\n')
                        export_file.write(chan.export_code+'\n')
                    export_file.flush()
                    self.export_filename = filename
                elif overwrite == 'merge':
                    with open(filename, 'r') as new_file:
                        new_btns = new_file.read()
                elif overwrite == 'load' or not len(self.export_btns_w.children):
                    if old_file:
                        old_file.close()
                    self.export_btns_w.clear_widgets()
                    self.export_file = open(filename, 'r+')
                    new_btns = self.export_file.read()
                    self.export_filename = filename
                    self.curr_export_btn = None
                elif overwrite == 'raise':
                    self.exception_handler('File already exists.'+
                    '\n\nWhat would you like to do?\n-Load the file and overwrite the current '+
                    'channels.\n-Merge the current channels with the file channels.\n-Overwrite the file with '+
                    'the current channels (overwrites the file on disk).\n-Browse for another file.\n-Cancel.',
                    partial(self.load_exporter, filename), 'data_res', 'File Conflict', delay=True)
                    return True
            except Exception as e:
                self.exception_handler(str(e), None, 'error', 'Error!', delay=True)
                return True
            if new_btns:
                new_btns = re.split('channel:(.*?)\n', new_btns)
                for i in range((len(new_btns)-1)/2):
                    self.add_export_btn(new_btns[i*2 + 1], new_btns[i*2 + 2].rstrip())
        else:
            self.exception_handler("You haven't opened a data file yet.", None, 'error', 'Error!')
            return True
        return True

    def add_export_btn(self, name='', code=''):
        if not self.data_filename:
            return
        btn = ToggleButton(group='export_btns')
        btn.text = name
        btn.export_code = code
        btn.export_result = ('', '')
        def set_export_btn(instance, *largs):
            if instance.state == 'down':
                self.curr_export_btn = None
                self.export_code_w.text = instance.export_code
                self.curr_export_btn = instance
            elif self.curr_export_btn == instance:
                self.curr_export_btn = None
        btn.bind(on_release=set_export_btn)
        self.export_btns_w.add_widget(btn)

    def edit_export_btn(self):
        if not self.data_filename:
            return
        curr = self.curr_export_btn
        if curr:
            curr.text = curr.export_code

    def create_export_data(self, filenames):
        if not self.data_filename:
            return
        try:
            filename = ''
            export_list = sorted(list(set(self.media.get_export_list())), reverse=True)
            p = re.compile('|'.join([re.escape(x) for x in export_list]))
            btns = [p.sub(lambda x:'d[\''+x.group()+'\']', btn.export_code) for btn in reversed(self.export_btns_w.children)]
            output = [[btn.text for btn in reversed(self.export_btns_w.children)]]
            if not filenames:
                raise Exception('A file has not been selected.')
            for filename in eval(filenames):
                d = tracker.TrackLog.import_data_file(filename)
                result = exporter.export_data(d, btns)
                output.append(result)
            self.export_output_w.result = output
            self.export_output_w.text = '\n'.join(['\t'.join(map(str, row)) for row in output]).expandtabs(16)
        except Exception as e:
            self.export_output_w.text = filename + ' : ' + str(type(e)) + ' : ' + str(e)
            self.export_output_w.result = []
        return True

    def save_export_data(self, filename, record_count, overwrite='raise'):
        if self.data_filename:
            if not filename.endswith('.csv'):
                filename += '.csv'
            filename = os.path.normpath(filename)
            try:
                if not self.export_output_w.result:
                    raise Exception("There's no data to save.")
                if filename == '.csv':
                    raise Exception('You have not provided a filename.')
                exists = os.path.exists(filename)
                if overwrite == 'overwrite' or not exists:
                    output = self.export_output_w.result
                    with open(filename, 'w') as export_file:
                        export_file.write('\n'.join([','.join(map(str, row)) for row in output]))
                        export_file.write('\n')
                        if not record_count:
                            return True
                        for row in output[1:]:
                            res = [[]]
                            src_file = ''
                            for i in range(len(row)):
                                if row[i].__class__ != exporter.DataResult:
                                    continue
                                curr = row[i].previous
                                count = 0
                                while count < record_count:
                                    if curr is None or curr.__class__ != exporter.DataList:
                                        break
                                    src_file = curr.d['_ID']
                                    res.append(['pts_'+output[0][i]+'_'+curr.func] + [str(curr.d['_pts'][pts]) for pts in curr.pts])
                                    res.append([output[0][i]+'_'+curr.func] + map(str, curr))
                                    curr = curr.previous
                                    count += 1
                            length = max([len(col) for col in res])
                            for col in res[1:]:
                                col.extend([''] * (length - len(col)))
                            res[0] = [src_file] * length
                            export_file.write('\n'.join([','.join([col[i] for col in res]) for i in range(length)]))
                            export_file.write('\n')
                elif overwrite == 'raise':
                    self.exception_handler('File already exists.'+
                    '\n\nWhat would you like to do?\n-Load the file and overwrite the current '+
                    'channels.\n-Merge the current channels with the file channels.\n-Overwrite the file with '+
                    'the current channels (overwrites the file on disk).\n-Browse for another file.\n-Cancel.',
                    partial(self.save_export_data, filename, record_count), 'data_res', 'File Conflict',
                    disabled=['load', 'merge'], delay=True)
                    return True
            except Exception as e:
                self.exception_handler(str(e), None, 'error', 'Error!', delay=True)
                return True
        else:
            self.exception_handler("You haven't opened a data file yet.", None, 'error', 'Error!')
            return True
        return True

    def test_export_chan(self, record_count):
        if not self.data_filename:
            return
        self.export_output_w.result = []
        export_list = sorted(list(set(self.media.get_export_list())), reverse=True)
        p = re.compile('|'.join([re.escape(x) for x in export_list]))
        if self.data_filename and self.curr_export_btn:
            try:
                d = tracker.TrackLog.import_data_file(self.data_filename)
                result = exporter.export_data(d, [p.sub(lambda x:'d[\''+x.group()+'\']',
                                                        self.curr_export_btn.export_code)])
                output = [['result', str(result[0])]]
                if record_count and result[0].__class__ == exporter.DataResult:
                    curr = result[0].previous
                    count = 0
                    while count < record_count:
                        if curr is None or curr.__class__ != exporter.DataList:
                            break
                        output.append(['pts_'+self.curr_export_btn.text+'_'+curr.func] + [str(d['_pts'][pts]) for pts in curr.pts])
                        output.append([self.curr_export_btn.text+'_'+curr.func] + map(str, curr))
                        curr = curr.previous
                        count += 1
                length = min(max([len(chan) for chan in output]), 250)
                for i in range(len(output)):
                    output[i] = output[i][:length]
                for i in range(len(output)):
                    output[i].extend([''] * (length - len(output[i])))
                self.export_output_w.text = '\n'.join(['\t'.join([chan[i] for chan in output])
                                                       for i in range(length)]).expandtabs(16)
            except Exception as e:
                self.export_output_w.text = str(type(e)) + ' : ' + str(e)
        return True


    def help(self):
        self.browse_w.ids['settings_btn'].state = 'normal'
        self.browse_w.ids['export_btn'].state = 'normal'
        self.browse_w.ids['dancing_btn'].state = 'normal'
        self.img_screen_w.current = 'help' if self.img_screen_w.current != 'help' else 'image'
    def open_user_info(self):
        self.user_comment_w.open()

    def exception_handler(self, msg, res_func, screen, title, disabled=[], delay=False):
        self.error_popup.err_message.text = msg
        self.error_popup.res_func = res_func
        self.error_popup.error_screen.current = PyTrackPopups[screen]
        self.error_popup.title = title
        if 'load' in disabled:
            self.error_popup.data_load_btn.disabled = True
        if 'merge' in disabled:
            self.error_popup.merge_btn.disabled = True
        if delay and self.error_popup._window:
            Clock.schedule_once(lambda *largs:self.error_popup.open(), 2)
        else:
            self.error_popup.open()


if __name__ == '__main__':

    old_write = kivy_handler._write_message
    def new_write(self, record):
        TrackApp.prog_log = str(TrackApp.prog_log) + '[%-18s] ' % record.levelname
        try:
            TrackApp.prog_log = str(TrackApp.prog_log) + record.msg
        except UnicodeEncodeError:
            if PY2:
                TrackApp.prog_log = str(TrackApp.prog_log) + record.msg.encode('utf8')
        TrackApp.prog_log = str(TrackApp.prog_log) + '\n'
        old_write(self, record)
    kivy_handler._write_message = new_write

    a= TrackApp()
    try:
        a.run()
    except:
        a.close_video()
        raise
    finally:
        kivy_handler._write_message = old_write
    a.close_video()
