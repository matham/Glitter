

__all__ = ('PyTrackException', 'PyTrackPopups')


PyTrackPopups = {'recover_autosave':'autosave',
                 'data_res':'data_choice',
                 'error':'default'}

class PyTrackException(Exception):
    exception_type = 'error'
    
    def __init__(self, exception_type='error', message='', **kwargs):
        super(PyTrackException, self).__init__(**kwargs)
        self.exception_type = exception_type
        self.message = message

    def __str__(self):
        return self.message
