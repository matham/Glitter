import colorsys

def to_bool(val):
    '''Takes anything and converts it to a bool type. If `val` is the `'False'`
    or `'0'` strings it also evaluates to False.

    :Parameters:

        `val`: object
            A value which represents True/False.

    :Returns:
        bool. `val`, evalutaed to a boolean.

    ::

        >>> to_bool(0)
        False
        >>> to_bool(1)
        True
        >>> to_bool('0')
        False
        >>> to_bool('1')
        True
        >>> to_bool('False')
        False
        >>> to_bool('')
        False
        >>> to_bool('other')
        True
        >>> to_bool('[]')
        True
    '''
    if val == 'False' or val == '0':
        return False
    return not not val


def color_complement(color):
    comp = list(colorsys.rgb_to_hsv(*color))  # find complement
    comp[0] += 0.5
    if comp[0] > 1:
        comp[0] -= 1
    comp = list(colorsys.hsv_to_rgb(*comp))
    if color[0:3] == [1, 1, 1]:
        comp = [0, 0, 0]
    elif color[0:3] == [0, 0, 0]:
        comp = [1, 1, 1]

    return color
