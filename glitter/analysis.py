
import numpy as np
from numpy.linalg import norm
from kivy.garden.collider import Collide2DPoly


def moving_average(data, n=1) :
    ret = np.cumsum(data, dtype=np.double, axis=0)
    ret[n:] = ret[n:] - ret[:-n]
    return ret[n - 1:] / float(n)


class Base(object):

    def _extract_from_indices(self, data, indices):
        data = [data[i][s:e] for i, s, e in indices if e > s]

    def _extract_from_range(
            self, data, start_group, start_idx, end_group, end_idx):
        if start_group >= len(data):
            return []

        new_data = [np.array(d) for d in data[start_group or 0:(end_group is None or len(data)) + 1]]
        if not new_data:
            return []

        if start_idx:
            new_data[0] = new_data[0][start_idx:]
            if not len(new_data[0]):
                del new_data[0]

        if end_group >= len(data):
            return new_data

        if end_idx is not None:
            new_data[-1] = new_data[-1][:end_idx - (start_idx or 0)]
            if not len(new_data[-1]):
                del new_data[-1]
        return new_data


class TimeTicks(Base):
    ticks = None

    def __init__(self, ticks, **kwargs):
        super(TimeTicks, self).__init__(**kwargs)
        self.ticks = tuple(ticks)

    def get_time(self, section, index):
        return self.ticks[section][index]

    def condition_interval(
            self, tstart=None, tend=None, start_offset=None, end_offset=None):
        ticks = self.ticks
        if tstart is None:
            if start_offset is None:
                tstart = ticks[0][0]
            else:
                tstart = ticks[0][0] + start_offset

        if tend is None:
            if end_offset is None:
                tend = ticks[-1][-1]
            else:
                tend = ticks[-1][-1] - start_offset

        return tstart, tend

    def extract_from_indices(self, indices):
        return TimeTicks(ticks=self._extract_from_indices(self.ticks, indices))

    def extract_from_range(self, start_group, start_idx, end_group, end_idx):
        return TimeTicks(
            ticks=self._extract_from_range(
                self.ticks, start_group, start_idx, end_group, end_idx))

    def get_range_values(
            self, tstart=None, tend=None, start_offset=None, end_offset=None):
        ts, te = self.condition_interval(tstart, tend, start_offset, end_offset)
        ticks = self.ticks
        sfound = efound = False
        for si, times in enumerate(ticks):
            for sj, t in enumerate(times):
                if ts <= t:
                    sfound = True
                    break
            if sfound:
                break

        if not sfound:
            return len(ticks), 0, len(ticks), 0

        for ei, times in enumerate(ticks[si:], si):
            s = sj if ei == si else 0
            for ej, t in enumerate(times[s:], s):
                if te <= t:
                    efound = True
                    break
            if efound:
                break

        if not efound:
            ei = len(ticks)
            ej = 0

        return si, sj, ei, ej


class Area(object):

    def __init__(self, width, height, closed_path):
        self.width = int(width)
        self.height = int(height)
        self.closed_path = closed_path
        self.collider = Collide2DPoly(
            [val for coordinate in closed_path for val in coordinate],
            cache=True)

    def __contains__(self, point):
        return point in self.collider


class Point(object):

    center = None

    def __init__(self, center, **kwargs):
        super(Point, self).__init__(**kwargs)
        self.center = np.array(center)

        shape = self.center.shape
        if shape != (2, ) and shape != (1, 2):
            raise Exception(
                '{} with shape {} is not a valid single point'.format(
                    self.center, shape))


class TicksData(Base):

    metadata = None
    ticks = None
    data = None

    def __init__(self, ticks, data, metadata=None):
        self.metadata = metadata
        self.ticks = ticks
        self.data = data

    def extract_from_indices(self, indices, ticks=None, metadata=None):
        if ticks is None:
            ticks = self.ticks.extract_from_indices(indices)
        return self.__class__(
            data=self.extract_from_indices(self.data, indices),
            ticks=ticks, metadata=metadata)

    def extract_from_range(self, start_group, start_idx, end_group, end_idx, ticks=None, metadata=None):
        if ticks is None:
            ticks = self.ticks.extract_from_range(
                start_group, start_idx, end_group, end_idx)
        return self.__class__(
            data=self._extract_from_range(
                self.data, start_group, start_idx, end_group, end_idx),
            ticks=ticks, metadata=metadata)

    def flatten_data(self):
        return np.concatenate(self.data)


class XYTData(TicksData):

    def within_area(self, areas, metadata=None):
        res = []
        for trace in self.data:
            arr = np.zeros(len(trace), dtype=np.bool8)
            for i, val in enumerate(trace):
                for mask in areas:
                    if val in mask:
                        arr[i] = True
                        break
            res.append(arr)
        return DigitalTData(ticks=self.ticks, data=res, metadata=metadata)

    def compute_distance_to_point(self, point, metadata=None):
        center = point.center
        return AnalogTData(
            data=[norm(elems - center, axis=1) for elems in self.data],
            ticks=self.ticks, metadata=metadata)

    def compute_distance_traveled(
            self, bin=2, overlap=1, dist_metadata=None, time_metadata=None):
        '''
        '''
        dists, ticks, dt = [], [], []
        if bin <= 1:
            for d, t in zip(self.data, self.ticks.ticks):
                dist = norm(d[1:] - d[:-1], axis=1)
                t_mean = (t[1:] + t[:-1]) / 2.
                t_diff = t[1:] - t[:-1]

                assert len(t_mean) == len(dist)
                dists.append(dist)
                ticks.append(t_mean)
                dt.append(t_diff)
        else:
            offset = max(1, bin - overlap)
            center = int(round(bin / 2.)) - 1
            for d, t in zip(self.data, self.ticks.ticks):
                mean_coords = moving_average(d, bin)[::offset]
                diff = mean_coords[1:] - mean_coords[:-1]
                dist = norm(diff, axis=1)

                resampled_t = t[center:-(bin - 1 - center):offset]
                t_mean = (resampled_t[1:] + resampled_t[:-1]) / 2.
                t_diff = resampled_t[1:] - resampled_t[:-1]

                assert len(t_mean) == len(dist)
                dists.append(dist)
                ticks.append(t_mean)
                dt.append(t_diff)

        ticks_new = TimeTicks(ticks=ticks)
        return (AnalogTData(
            data=dists, ticks=ticks_new, metadata=dist_metadata),
                AnalogTData(
            data=dt, ticks=ticks_new, metadata=time_metadata))


class AnalogTData(TicksData):

    pass


class DigitalTData(TicksData):

    _indices = None

    def __init__(self, indices=None, **kwargs):
        super(DigitalTData, self).__init__(**kwargs)

        if indices is not None:
            self._indices = indices

    @property
    def indices_set(self):
        if self._indices is not None:
            return self._indices

        self._indices = indices = []
        for j, state in enumerate(self.data):
            start = -1

            for i in range(len(state)):
                if state[i] and start == -1:
                    start = i

                if start != -1 and (i + 1 == len(state) or not state[i + 1]):
                    indices.append((j, start, i + 1))
                    start = -1

        return indices

    @property
    def event_count(self):
        return len(self.indices_set)

    @property
    def event_start_times(self):
        t = self.ticks.get_time
        indices = self.indices_set
        vals = np.zeros(len(indices))

        for j, (i, s, e) in enumerate(indices):
            vals[j] = t(i, s)
        return vals

    @property
    def event_end_times(self):
        t = self.ticks.get_time
        indices = self.indices_set
        vals = np.zeros(len(indices))

        for j, (i, s, e) in enumerate(indices):
            vals[j] = t(i, e - 1)
        return vals

    @property
    def event_durations(self):
        t = self.ticks.get_time
        indices = self.indices_set
        vals = np.zeros(len(indices))

        for j, (i, s, e) in enumerate(indices):
            assert e >= s
            vals[j] = t(i, e - 1) - t(i, s)

        return vals

    def clear_outside_interval(
            self, tstart=None, tend=None, start_offset=None, end_offset=None,
            metadata=None):
        ticks = self.ticks
        tstart, tend = ticks.condition_interval(
            tstart=tstart, tend=tend, start_offset=start_offset,
            end_offset=end_offset)
        data = [np.array(x) for x in self.data]

        for times, values in zip(ticks.ticks, data):
            for i, t in enumerate(times):
                if tstart <= t < tend:
                    continue
                values[i] = False

        return DigitalTData(data=data, ticks=ticks, metadata=metadata)
