import operator
from kivy.garden.collider import Collide2DPoly
import itertools

__all__ = ('DataList', )

class DataList(list):

    def __init__(self, d, score_type, name, func='', previous=None, *largs, **kwargs):
        super(DataList, self).__init__(*largs, **kwargs)
        self.score_type = score_type
        ''' Possible score_type are xyt, xy, t, pts '''
        self.previous = previous
        self.name = name
        self.func = func
        self.pts = []
        self.d = d

    def compare_constant(self, value, op):
        if value.__class__ is not float and value.__class__ is not int:
            raise Exception('Invalid data type, %s, given to %s comparison operator.' %(type(value), op))
        if self.score_type != 'pts':
            raise Exception("You can use the %s comparison operator only on pts." %op)
        result = DataList(self.d, 't', self.name, '%s_%f_%s' % (op, float(value), self.name))
        result.pts = self.pts
        op = getattr(operator, op)
        result[:] = [op(t, value) for t in self.d['_pts']]
        return result
    def __lt__(self, val):
        return self.compare_constant(val, 'lt')
    def __le__(self, val):
        return self.compare_constant(val, 'le')
    def __gt__(self, val):
        return self.compare_constant(val, 'gt')
    def __ge__(self, val):
        return self.compare_constant(val, 'ge')

    def within_dist(self, value):
        if value.__class__ is not float and value.__class__ is not int:
            raise Exception('Invalid data type, %s, used in within_dist.' %type(value))
        if self.score_type != 't':
            raise Exception("You can use the within_dist operator only on t score types.")
        result = DataList(self.d, 't', self.name, 'within_dist_%f_%s' % (float(value), self.name), self)
        result.pts = self.pts
        pts = self.d['_pts']
        result[:] = [False, ] * len(self)
        points = [pts[i] for i in range(len(self)) if self[i]]
        for i in range(len(result)):
            if value >= 0:
                result[i] = any([point <= pts[i] < point + value for point in points])
            else:
                result[i] = any([point + value < pts[i] <= point for point in points])
        return result

    def __or__(self, other):
        if other.__class__ is not DataList:
            raise Exception('Invalid data type given to or (|).')
        score_types = (self.score_type, other.score_type)
        if 'pts' in score_types:
            raise Exception("You cannot 'or' pts type data.")
        if score_types[0] == score_types[1]:
            if score_types[0] != 't':
                raise Exception("You can only 'or' identical data types if they are both of type t.")
            if len(self) != len(other):
                raise Exception("You can only 'or' data types t if they are both of the same length.")
            result = DataList(self.d, self.score_type, self.name, 'or_'+other.name, self)
            result.pts = self.pts
            result.extend([self[i] or other[i] for i in range(len(self))])
            return result
        raise Exception("You cannot 'or' a "+score_types[0]+' type with a '+score_types[1]+' type.')

    def __invert__(self):
        if self.score_type != 't':
            raise Exception("You can only 'invert' t type data.")
        result = DataList(self.d, self.score_type, self.name, 'invert_' + self.name, self)
        result.pts = self.pts
        result[:] = [not val for val in self]
        return result

    def __and__(self, other):
        if not isinstance(other, (DataList, tuple)):
            raise Exception('Invalid data type given to and (&).')
        if isinstance(other, tuple):
            score_type = self.score_type
            if 'pts' == score_type:
                raise Exception("You cannot 'and' pts type data.")
            if score_type != 't':
                raise Exception("You can only 'and' identical data types if they are both of type t.")
            result = DataList(self.d, self.score_type, self.name, 'and_'+str(other), self)
            pts = result.pts = self.pts
            pts0 = pts[0]
            if len(other) == 1:
                s, e = other[0] + pts0, pts[-1]
            else:
                s, e = other
                s, e = s + pts0, e + pts0
            result.extend([self[i] and s <= pts[i] <= e for i in range(len(self))])
            return result
        score_types = (self.score_type, other.score_type)
        if 'pts' in score_types:
            raise Exception("You cannot 'and' pts type data.")
        if score_types[0] == score_types[1]:
            if score_types[0] != 't':
                raise Exception("You can only 'and' identical data types if they are both of type t.")
            if len(self) != len(other):
                raise Exception("You can only 'and' data types t if they are both of the same length.")
            result = DataList(self.d, self.score_type, self.name, 'and_'+other.name, self)
            result.pts = self.pts
            result.extend([self[i] and other[i] for i in range(len(self))])
            return result
        if 't' in score_types:
            raise Exception("You cannot 'and' a "+score_types[0]+' type with a '+score_types[1]+' type.')
        a, b = self, other
        if score_types[0] == 'xyt':
            a, b = b, a
        collider = Collide2DPoly([p for p in itertools.chain.from_iterable(a)], cache=True)
        result = DataList(b.d, 't', b.name, 'and_'+a.name, b)
        result.pts = b.pts
        result.extend([b[i] in collider for i in range(len(b))])
        return result

# A scaler result from an operation on array
class DataResult(float):

    def __new__(cls, previous=None, *largs, **kwargs):
        obj = float.__new__(cls, *largs, **kwargs)
        obj.previous = previous
        return obj

def esum(data):
    return DataResult(data, sum(data))
def emin(data):
    return DataResult(data, min(data))
def emax(data):
    return DataResult(data, max(data))
def elen(data):
    return DataResult(data, len(data))

def event(data):
    if data.__class__ is not DataList:
        raise Exception('Invalid data type given to event().')
    if data.score_type != 't':
        raise Exception('Only t type channels can be given to event().')
    pts = data.d['_pts']
    result = DataList(data.d, data.score_type, data.name, 'event', data)
    start = -1
    for i in range(len(data)):
        if data[i] and start == -1:
            start = i
        if start != -1 and (i + 1 == len(data) or not data[i + 1]):
            result.append(pts[i] - pts[start])
            result.pts.append(start)
            start = -1
    return result

def export_data(d, channels):
    result = [0, ] * len(channels)
    for i in range(len(channels)):
        lines = channels[i].split('\n')
        lines = [line for line in lines if line]
        exec('\n'.join(lines[:-1]))
        result[i] = eval(lines[-1])
    return result
