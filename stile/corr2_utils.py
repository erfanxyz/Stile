"""@file corr2_utils.py
Contains elements of Stile needed to interface with Mike Jarvis's corr2 program.
"""
import copy
import numpy

# A dictionary containing all corr2 command line options.  (At the moment we only support v X.x, so
# only one dict is here; later versions of Stile may need to implement if statements here for the
# corr2 versions.)  The options themselves are mapped onto dicts with the following keys: 
#    'type': a tuple of the allowed input types.  
#    'val' : if the value must be one of a limited set of options, they are given here; else None.
#    'status': whether or not this is a corr2 option that Stile will pass through without 
#              altering.  The options are 'disallowed_computation' (Stile makes these choices),
#              'disallowed_file' (the DataHandler makes these choices), 'captured' (Stile should 
#              have harvested this for its own use--if it didn't that's a bug); and 'allowed' 
#              (Stile should silently pass it through to corr2).
options = {
    'file_name': 
        {'type': (str,list),
         'val': None,
         'status': 'captured'},
    'do_auto_corr': 
        {'type': (bool,),
         'val': None,
         'status': 'disallowed_computation'},
    'do_cross_corr':
        {'type': (bool,),
         'val': None,
         'status': 'disallowed_computation'},
    'file_name2': 
        {'type': (str,list),
         'val': None,
         'status': 'captured'},
    'rand_file_name': 
        {'type': (str,list),
         'val': None,
         'status': 'captured'},
    'rand_file_name2': 
        {'type': (str,list),
         'val': None,
         'status': 'captured'},
    'file_list': 
        {'type': (str,list),
         'val': None,
         'status': 'disallowed_file'},
    'file_list2': 
        {'type': (str,list),
         'val': None,
         'status': 'disallowed_file'},
    'rand_file_list': 
        {'type': (str,list),
         'val': None,
         'status': 'disallowed_file'},
    'rand_file_list2': 
        {'type': (str,list),
         'val': None,
         'status': 'disallowed_file'},
    'file_type': 
        {'type': (str,),
         'val': ("ASCII","FITS"),
         'status': 'captured'},
    'delimiter': 
        {'type': (str,),
         'val': None,
         'status': 'captured'},
    'comment_marker': 
        {'type': (str,),
         'val': None,
         'status': 'captured'},
    'first_row':
        {'type': (int,),
         'val': None,
         'status': 'captured'},
    'last_row':
        {'type': (int,),
         'val': None,
         'status': 'captured'},
    'x_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'y_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'ra_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'dec_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'x_units':
        {'type': (str,),
         'val': None,
         'status': 'allowed'},
    'y_units':
        {'type': (str,),
         'val': None,
         'status': 'allowed'},
    'ra_units':
        {'type': (str,),
         'val': None,
         'status': 'allowed'},
    'dec_units':
        {'type': (str,),
         'val': None,
         'status': 'allowed'},
    'g1_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'g2_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'k_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'w_col':
        {'type': (int,str),
         'val': None,
         'status': 'captured'},
    'flip_g1':
        {'type': (bool,),
         'val': None,
         'status': 'captured'},
    'flip_g2':
        {'type': (bool,),
         'val': None,
         'status': 'captured'},
    'pairwise':
        {'type': (bool,),
         'val': None,
         'status': 'disallowed_computation'},
    'project':
        {'type': (bool,),
         'val': None},
         'status': 'allowed',
    'project_ra':
        {'type': (float,),
         'val': None,
         'status': 'allowed'},
    'project_dec':
        {'type': (float,),
         'val': None,
         'status': 'allowed'},
    'min_sep':
        {'type': (float,),
         'val': None,
         'status': 'captured'},
    'max_sep':
        {'type': (float,),
         'val': None,
         'status': 'captured'},
    'nbins':
        {'type': (float,),
         'val': None,
         'status': 'captured'},
    'bin_size':
        {'type': (float,),
         'val': None,
         'status': 'captured'},
    'sep_units':
        {'type': (str,),
         'val': None,
         'status': 'allowed'},
    'bin_slop':
        {'type': (float,),
         'val': None,
         'status': 'allowed'},
    'smooth_scale':
        {'type': (float,),
         'val': None,
         'status': 'allowed'},
    'n2_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'n2_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'n2_statistic':
        {'type': (str,),
         'val': ['compensated','simple'],
         'status': 'allowed'},
    'ng_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'ng_statistic':
        {'type': (str,),
         'val': ['compensated','simple'],
         'status': 'allowed'},
    'g2_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'nk_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'nk_statistic':
        {'type': (str,),
         'val': ['compensated','simple'],
         'status': 'allowed'},
    'k2_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'kg_file_name':
        {'type': (str,),
         'val': ['compensated','simple'],
         'status': 'disallowed_file'},
    'precision': 
        {'type': (int,),
         'val': None,
         'status': 'allowed'},
    'm2_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'm2_uform':
        {'type': (str,),
         'val': ['Schneider','Crittenden'],
         'status': 'allowed'},
    'nm_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'norm_file_name':
        {'type': (str,),
         'val': None,
         'status': 'disallowed_file'},
    'verbose': 
        {'type': (int,),
         'val': None,
         'status': 'captured'},
    'num_threads':
        {'type': (int,),
         'val': None,
         'status': 'captured'},
    'split_method':
        {'type': (str,),
         'val': ["mean","median","middle"],
         'status': 'allowed'}}

# column_maps is a dict of the column names for all the corr2 output file types.  Sometimes there
# are different numbers of columns for the same file type depending on options.  Right now, however,
# the possible numbers of columns are not degenerate, so we can match it up simply by checking
# for the list of column names with the right length.
column_maps = {
    'n2': [
            ['r_nominal','r_mean','omega','sig_omega','dd','rr'],
            ['r_nominal','r_mean','omega','sig_omega','dd','rr','dr','rd'] ],
    'ng': [
            ['r_nominal','r_mean','gamt','gamx','sig'],
            ['r_nominal','r_mean','gamt','gamx','sig','weight','npairs','gamT_d','gamX_d',
             'weight_d','npairs_d','gamT_r','gamX_r','weight_r','npairs_r'],
            ['r_nominal','r_mean','gamt','gamx','sig','r_sm','gamT_sm','sig_sm'],
            ['r_nominal','r_mean','gamt','gamx','sig','weight','npairs','gamT_d','gamX_d',
             'weight_d','npairs_d','gamT_r','gamX_r','weight_r','npairs_r','r_sm','gamT_sm',
             'sig_sm'] ],
    'g2': [
        ['r_nominal','r_mean','xi+','xi-','xi+_im','xi-_im','sig_xi','weight','npairs'],
        ['r_nominal','r_mean','xi+','xi-','xi+_im','xi-_im','sig_xi','weight','npairs',
         'r_sm','xi+_sm','xi-_sm','sig_sm'] ],
    'nk': [
        ['r_nominal','r_mean','kappa_mean','sig','weight','npairs'],
        ['r_nominal','r_mean','kappa_mean','sig','kappa_d','weight_d','pairs_d','kappa_r',
         'weight_r','npairs_r'],
        ['r_nominal','r_mean','kappa_mean','sig','weight','npairs','r_sm','kappa_sm','sig_sm'],
        ['r_nominal','r_mean','kappa_mean','sig','kappa_d','weight_d','pairs_d','kappa_r',
         'weight_r','npairs_r','r_sm','kappa_sm','sig_sm'] ],
    'k2': [
        ['r_nominal','r_mean','xi','sig_xi','weight','npairs'],
        ['r_nominal','r_mean','xi','sig_xi','weight','npairs','r_sm','xi_sm','sig_sm'] ],
    'kg': [
        ['r_nominal','r_mean','kgamT_mean','kgamX_mean','sig','weight','npairs'],
        ['r_nominal','r_mean','kgamT_mean','kgamX_mean','sig','kgamT_d','kgamX_d','weight_d',
         'npairs_d','kgamT_r','kgamX_r','weight_r','npairs_r'],
        ['r_nominal','r_mean','kgamT_mean','kgamX_mean','sig','weight','npairs','r_sm','kgamT_sm',
         'sig_sm'],
        ['r_nominal','r_mean','kgamT_mean','kgamX_mean','sig','kgamT_d','kgamX_d','weight_d',
         'npairs_d','kgamT_r','kgamX_r','weight_r','npairs_r','r_sm','kgamT_sm','sig_sm'] ],
    'm2': [
        ['r','map^2_mean','mx^2_mean','mmx_mean_a','mmx_mean_b','sig_map','gam^2_mean','sig_gam']],
    'nm': [
        ['r','nmap_mean','nmx_mean','sig_nmap'] ],
    'norm': [
        ['r','nmap_mean','nmx_mean','sig_nm','n^2_mean','sig_n^2','map^2_mean','sig_mm','nmnorm',
         'sig_nmnorm','nnnorm','sig_nnnorm'] ]
}

def check_options(input_dict, check_status=True):
    """
    A function that checks the (key,value) pairs of the dict passed to it against the corr2 options 
    dict.  If the key is not understood, or if check_status is True and the key is not allowed or 
    should have been captured by the main Stile program, an error is raised.  If the key is allowed,
    the type and/or values are checked against the corr2 requirements.
    
    @param input_dict   A dict which will be used to write a corr2 param file
    @param check_status A flag indicating whether to check the status of the keys in the dict.  This
                        should be done when eg reading in arguments from the command line; later 
                        checks for type safety, after Stile has added its own parameters, shouldn't
                        do it.  (default: True)
    @returns            The input dict, unchanged.            
    """
    
    for key in input_dict:
        if key not in options:
            raise ValueError('Option %s not understood by Stile and not a recognized corr2 '
                               'option.  Please check syntax and try again.'%key)                         
        else:
            ok = options[key]
            if ok['status']=='disallowed_file':
                raise ValueError('Option %s for corr2 is forbidden by Stile, which may need to '
                                 'write multiple output files of this type.  Please remove this '
                                 'option from your syntax, and check the documentation for where '
                                 'the relevant output files will be located.'%key)
            elif ok['status']=='disallowed_computation':
                raise ValueError('Option %s for corr2 is forbidden by Stile, which controls '
                                 'the necessary correlation functions.  Depending on your needs, '
                                 'please either remove this option from your syntax or consider '
                                 'running corr2 as a standalone program.'%key)
            elif ok['status']=='captured':
                raise ValueError('Option %s should have been captured by the input parser for '
                                 'Stile, but it was not.  This is a bug; please '
                                 'open an issue at http://github.com/msimet/Stile/issues.'%key)
            if type(input_dict[key]) not in ok['type']:
                # The unknown arguments are passed as strings.  Since the string may not be the
                # desired option, try casting the value into the correct type or types and see if
                # it works or raises an error; if at least one works, pass, else raise an error.
                type_ok = False
                for options_type in ok['type']:
                    try:
                        options_type(input_dict[key])
                        type_ok=True
                    except:
                        pass
                if not type_ok:
                    raise ValueError("Option %s is a corr2 option, but the type of the given "
                                     "argument %s does not match corr2's requirements.  Please "
                                     "check syntax and try again."%(key,input_dict[key]))
            if ok['val']:
                if input_dict[key] not in ok['val']:
                    raise ValueError('Corr2 option %s only accepts the values [%s].  Please '
                                     'check syntax and try again.'%(key,', '.join(ok['val'])))
    return input_dict
    
def write_corr2_param_file(param_file_name,**kwargs):
    """
    Write the given kwargs to a corr2 param file if they are in the options dict above.  If the
    value of a (key,value) pair is a dict, this function is called recursively on the items in the 
    dict, to allow a separate (eg) corr2_options dict that gets handed around Stile without 
    interference, in addition to the arguments that corr2 needs to run.  
    
    @param param_file_name May be a file name or any object with a .write(...) attribute.
    @param kwargs          A set of corr2 parameters, represented as a dict.
    """
    
    if isinstance(param_file_name,str):
        f=open(param_file_name)
        close_file=True
    else:
        f=param_file_name
        close_file=False
    for key in kwargs:
        if key in options:
            f.write(key+' = ' + kwargs[key]+'\n')
        elif isinstance(kwargs[key],dict):
            write_corr2_param_file(f,kwargs[key])
        else:
            raise ValueError("Unknown key %s passed to write_corr2_param_file.  This is a bug; "
                             "please check your code if it's yours, or open an issue at "
                             "http://github.com/msimet/Stile/issues if it's ours."%key)
    if close_file:
        f.close()
        
def read_corr2_output_file(file_name,file_type):
    """
    Read in the given file_name of type file_type.  Cast it into a numpy.recarray with the
    appropriate column mappings from column_maps and return it.
    
    @param file_name The location of an output file from corr2.
    @param file_type The type of correlation function that was run; available options can be found
                     by printing the keys of corr2_utils.column_maps or checking the corr2
                     documentation.
    @returns         A numpy.recarray corresponding to the data in file_name.
    """    
    import stile_utils
    if file_type not in column_maps:
        raise ValueError('Unknown file_type %s in corr2_utils.read_corr2_output_file. Available ' 
                           'file types are: %s.'%' '.join(sorted(column_maps.keys())))
    output = numpy.loadtxt(file_name)
    if not output:
        raise RuntimeError('File %s (supposedly an output from corr2) is empty.'%file_name)
    lenline = output.shape[-1]
    use_col_map = None
    for col_map in column_maps[file_type]:
        if len(col_list)==lenline:
            use_col_map = col_map
    if not use_col_map:
        raise RuntimeError('Output from corr2 (file %s) does not have a number of columns '
                           'corresponding to a column mapping that corr2_utils knows for file_type '
                           '%s.'%(file_name,file_type))
    return stile_utils.make_recarray(output,cols=use_col_map,only_floats=True)

def add_corr2_dict(input_dict):
    """
    Take an input_dict, harvest the options you'll need for corr2, and create a new 'corr2_options'
    key in the input_dict containing these values (or update the existing 'corr2_options' key).
    
    @param input_dict A dict containing some (key,value) pairs that apply to corr2
    @returns          The input_dict with an added or updated key 'corr2_options' whose value is a
                      dict containing the (key,value) pairs from input_dict that apply to corr2
    """    
    corr2_dict={}
    for key in options:
        if key in input_dict:
            corr2_dict[key] = input_dict[key]
    if 'corr2_options' in input_dict:
        input_dict['corr2_options'].update(corr2_dict)
    else:
        input_dict['corr2_options'] = corr2_dict
    return input_dict
    
