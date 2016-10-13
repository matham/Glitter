



__all__ = ('HelpDoc')


HelpDoc = '''
[b]Browsing bar:[/b]

[b]Load video:[/b] Loads a video file. If set to load a default data file, it \
also loads or create a data file with the same name as the video file. It closes\
any previously opened video and data files. Current channels will not be deleted.
 
[b]Load data file:[/b] Loads or creates a data file. All the recorded data\
is stored in the PyTables HDF5 format data file.


[b]Exporter:[/b]
The following file level variables are available in the exporter:
_version (provides the version of the program which wrote the file).
_filename (the filename of the video file associated with the data file).
_vid_info (a dict with information about the video file, e.g. frame size...).
_user (the user that created the file).
_ID (the filename of the video file associated with the data file).
_complete (whether all the frames in the video has been watched).
_pts (the list of the timestamps of the video).

In addition, each channel's name defined in the data file is also available in \
two flavors. For example, say you add a two channels, Head, and Tail in that \
order. Then you can refer to them using either Head, Tail respectively, \
or Head_0, Tail_1, respectively. That is, you can refer to each channel by \
its name, or by appending _n, where n is the order number of the channel, \
defined by the order in which the channels were created. This should resolve \
naming conflicts.
'''