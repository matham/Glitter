from math import floor, ceil
from array import array
import colorsys

from kivy.uix.widget import Widget
from kivy.properties import NumericProperty, VariableListProperty, ListProperty
from kivy.properties import ObjectProperty
from kivy.lang import Builder
from kivy.graphics.texture import Texture
from kivy.clock import Clock


Builder.load_string('''
#:import floor math.floor
<StateIndicator>
    n_bins: int(floor(self.effective_width))
    texture_size: self.n_bins, len(self.channels) * self.line_pixels + \
        max(0, len(self.channels) - 1) * self.sep_pixels
    ratio: self.effective_width / float(self.max_scale)
    effective_width: max(0, self.width - self.padding[0] - self.padding[2])
    minimum_height: self.padding[1] + self.padding[3] + \
        len(self.channels) * self.line_pixels + \
        max(0, len(self.channels) - 1) * self.sep_pixels
    height: self.texture_size[1] + self.padding[1] + self.padding[3]
    size_hint_y: None
    on_width:
        self.compute_ticks()
        self.compute_channels()
        self.draw_channels()
    on_selection: print(args)

    canvas:
        Color:
            rgb: 1, 1, 1
        Rectangle:
            pos: self.x + self.padding[0], self.y + self.padding[3]
            size: self.texture_size
            texture: self.texture
''')


class StateIndicator(Widget):

    __events__ = ('on_selection', )

    line_pixels = NumericProperty(1)

    sep_pixels = NumericProperty(1)

    padding = VariableListProperty(0, length=4)

    effective_width = NumericProperty(0)

    max_chans = NumericProperty(1)

    minimum_height = NumericProperty(0)

    max_scale = NumericProperty(1)

    ratio = NumericProperty(1)
    '''Multiply by external units to get offset in internal unit.
    '''

    n_bins = NumericProperty(1)

    texture_size = ListProperty([0, 0])

    _last_size = None

    _buffer = None

    texture = ObjectProperty(None)

    channels = ListProperty([])

    ticks = ListProperty([])

    ticks_count = []

    unit_ticks_count = 10

    _was_multi_tap = False

    _trigger = None

    def __init__(self, **kwargs):
        super(StateIndicator, self).__init__(**kwargs)
        self.ticks_count = []
        fbind = self.fbind
        fbind('line_pixels', self._compute_max_chans)
        fbind('sep_pixels', self._compute_max_chans)
        fbind('padding', self._compute_max_chans)
        fbind('height', self._compute_max_chans)
        fbind('on_selection', self.highlight_region)
        self.compute_ticks()

    def _compute_max_chans(self, *largs):
        l, t, r, b = self.padding
        sep_pixels = self.sep_pixels
        line_pixels = self.line_pixels
        effective_height = max(0, self.height - t - b)

        if effective_height < line_pixels:
            self.max_chans = 0
        else:
            self.max_chans = 1 + floor((effective_height - line_pixels) /
                                       (sep_pixels + line_pixels))

    def add_channel(self, index=None, color=(1, 1, 1)):
        channels = self.channels
        val = {'points': [], 'counts': [],
               'color': map(int, [c * 255 for c in color])}

        if index is None:
            idx = len(channels)
            channels.append(val)
        else:
            idx = index
            channels.insert(val)
        self.compute_channels(istart=idx, iend=idx + 1)
        self.draw_channels(istart=idx)

    def remove_channel(self, index):
        del self.channels[index]
        self.draw_channels(istart=index)

    def compute_channels(self, istart=None, iend=None):
        channels = self.channels
        if istart is None:
            istart = 0
        if iend is None:
            iend = len(channels)
        n = self.n_bins
        ratio = n / float(self.max_scale)

        for data in channels[istart:iend]:
            counts = data['counts']
            counts[:] = [0, ] * n
            if n:
                for val in data['points']:
                    counts[int(min(floor(val * ratio), n - 1))] += 1

    def compute_ticks(self):
        n = self.n_bins
        if n:
            ratio = n / float(self.max_scale)
            counts = self.ticks_count = [0, ] * n

            for val in self.ticks:
                counts[min(floor(val * ratio), n - 1)] += 1

    def draw_channels(self, istart=None, iend=None, pos=None):
        channels = self.channels
        if istart is None:
            istart = 0
        if iend is None:
            iend = len(channels)
        bin = None if pos is None else self.to_internal(pos)
        n = self.n_bins

        tsize = self.texture_size
        if not tsize[0] or not tsize[1] or not n:
            self.texture = None
            return

        if tsize != self._last_size or not self.texture:
            tex = self.texture = Texture.create(size=tsize)
            buf = self._buffer = array('B', [0, ] * (tsize[0] * tsize[1] * 3))
            istart, iend = 0, len(channels)
        else:
            tex = self.texture
            buf = self._buffer

        ticks = self.ticks_count
        def_ticks = self.unit_ticks_count
        line_pixels = self.line_pixels
        sep_pixels = self.sep_pixels
        l = 0

        for data in channels[istart:iend]:
            for bin, (count, tick) in enumerate(zip(data['counts'], ticks)):
                ratio = min(1, count / float(tick if tick else def_ticks))
                r, g, b = data['color']
                r = int(r * ratio)
                g = int(g * ratio)
                b = int(b * ratio)

                for line in range(l, l + line_pixels):
                    s = (line * n + bin) * 3
                    buf[s] = r
                    buf[s + 1] = g
                    buf[s + 2] = r

            l += line_pixels + sep_pixels

        tex.blit_buffer(buf, colorfmt='rgb', bufferfmt='ubyte')

    def to_internal(self, pos):
        n = self.n_bins
        return max(min(floor(pos / float(self.max_scale) * n), n - 1), 0)

    def add_channel_tick(self, channel, pos):
        data = self.channels[channel]
        data['points'].append(pos)
        if self.n_bins:
            data['counts'][self.to_internal(pos)] += 1
            self.draw_channels(channel, channel + 1, pos)

    def remove_channel_tick(self, channel, pos):
        data = self.channels[channel]
        data['points'].remove(pos)
        if self.n_bins:
            data['counts'][self.to_internal(pos)] -= 1
            self.draw_channels(channel, channel + 1, pos)

    def add_tick(self, pos):
        self.ticks.append(pos)
        if self.n_bins:
            self.ticks_count[self.to_internal(self.to_internal(pos))] += 1
            self.draw_channels(pos=pos)

    def on_touch_down(self, touch):
        if super(StateIndicator, self).on_touch_down(touch):
            return
        if not self.collide_point(*touch.pos):
            return False

        triple = touch.is_double_tap
        double = touch.is_double_tap
        if (double or triple) and self._was_multi_tap:
            return False

        l, t, r, b = self.padding
        self._was_multi_tap = triple or double
        ew = self.effective_width
        if not ew:
            return False

        x = touch.x - self.x - self.padding[0]
        if x >= ew or x < 0:  # ensure it's not in the padding
            return False

        y = touch.y - self.y - self.padding[3]
        if y < 0 or y >= self.minimum_height:
            return False

        if triple:
            fmt = 'chan'
        elif double:
            fmt = 'event'
        else:
            fmt = 'frame'

        line_p = self.line_pixels
        sep_p = self.sep_pixels
        channels = self.channels
        if y < line_p + sep_p / 2.:
            i = 0
        else:
            i = int(floor((y - (line_p + sep_p / 2.)) / float(line_p + sep_p)))
            i = max(min(i + 1, len(channels) - 1), 0)

        self.dispatch('on_selection', i, x / ew * self.max_scale, fmt)

    def highlight_region(self, instance, chan, pos, fmt):
        pass

    def on_selection(self, chan, pos, fmt):
        pass


if __name__ == '__main__':
    from kivy.app import runTouchApp

    class MyIndicator(StateIndicator):

        def __init__(self, **kwargs):
            super(MyIndicator, self).__init__(**kwargs)
            self.add_channel()
            self.add_channel()
            self.add_channel()
            self.add_channel()
            for i in range(1):
                self.add_channel_tick(0, 25)
                self.add_channel_tick(1, 50)
                self.add_channel_tick(2, 75)
                self.add_channel_tick(3, 90)

        def on_touch_down(self, touch):
            if self.mode == 'normal':
                return super(MyIndicator, self).on_touch_down(touch)

    runTouchApp(Builder.load_string('''
BoxLayout:

    MyIndicator:
        mode: but.state
        max_scale: 100
        line_pixels: 10
        sep_pixels: 16
    ToggleButton:
        id: but
        text: 'add'
        size_hint_y: .2
'''))
