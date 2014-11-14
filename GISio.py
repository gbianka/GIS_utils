# suppress annoying pandas openpyxl warning
import warnings
warnings.filterwarnings('ignore', category=UserWarning)

import numpy as np
import osr, gdal
import fiona
from shapely.geometry import Point, shape, asLineString, mapping
from shapely.wkt import loads
import pandas as pd
import shutil

def getPRJwkt(epsg):
   """
   from: https://code.google.com/p/pyshp/wiki/CreatePRJfiles

   Grab an WKT version of an EPSG code
   usage getPRJwkt(4326)

   This makes use of links like http://spatialreference.org/ref/epsg/4326/prettywkt/
   """
   import urllib
   f=urllib.urlopen("http://spatialreference.org/ref/epsg/{0}/prettywkt/".format(epsg))
   return (f.read())


def shp2df(shp, index=None, geometry=False):
    '''
    Read shapefile into Pandas dataframe
    shp = shapefile name
    '''
    print "\nreading {}...".format(shp)
    shp_obj = fiona.open(shp, 'r')

    attributes_dict = {}
    knt = 0
    length = len(shp_obj)
    for line in shp_obj:
        props = line['properties']
        if geometry:
            geometry = shape(line['geometry'])
            props['geometry'] = geometry
        attributes_dict[line['id']] = props
        knt += 1
        print '\r{:d}%'.format(100*knt/length),

    print '--> building dataframe... (may take a while for large shapefiles)'
    shp_df = pd.DataFrame.from_dict(attributes_dict, orient='index')

    if index:
        try:
            index = [c for c in shp_df.columns if c.lower() == index.lower()][0]
        except IndexError:
            print "Index column not found."
        shp_df.index = shp_df[index]
    
    return shp_df


def shp_properties(df):
    # convert dtypes in dataframe to 32 bit
    i = -1
    dtypes = list(df.dtypes)
    for dtype in dtypes:
        i += 1
        if dtype == np.dtype('float64'):
            continue
        # need to convert integers to 16-bit for shapefile format
        #elif dtype == np.dtype('int64') or dtype == np.dtype('int32'):
        elif 'float' in dtype.name:
            df[df.columns[i]] = df[df.columns[i]].astype('float64')
        elif dtype == np.dtype('int64'):
            df[df.columns[i]] = df[df.columns[i]].astype('int32')
        elif dtype == np.dtype('bool'):
            df[df.columns[i]] = df[df.columns[i]].astype('str')
    # strip dtypes just down to 'float' or 'int'
    dtypes = [''.join([c for c in d.name if not c.isdigit()]) for d in list(df.dtypes)]
    #dtypes = [d.name for d in list(df.dtypes)]
    # also exchange any 'object' dtype for 'str'
    dtypes = [d.replace('object', 'str') for d in dtypes]
    properties = dict(zip(df.columns, dtypes))
    return properties


def shpfromdf(df, shpname, Xname, Yname, prj):
    '''
    creates point shape file from pandas dataframe
    shp: name of shapefile to write
    Xname: name of column containing Xcoordinates
    Yname: name of column containing Ycoordinates
    '''
    '''
    # convert dtypes in dataframe to 32 bit
    i = -1
    dtypes = list(df.dtypes)
    for dtype in dtypes:
        i += 1
        if dtype == np.dtype('float64'):
            continue
            #df[df.columns[i]] = df[df.columns[i]].astype('float32')
        elif dtype == np.dtype('int64'):
            df[df.columns[i]] = df[df.columns[i]].astype('int32')
    # strip dtypes just down to 'float' or 'int'
    dtypes = [''.join([c for c in d.name if not c.isdigit()]) for d in list(df.dtypes)]
    # also exchange any 'object' dtype for 'str'
    dtypes = [d.replace('object', 'str') for d in dtypes]

    properties = dict(zip(df.columns, dtypes))
    '''
    properties = shp_properties(df)
    schema = {'geometry': 'Point', 'properties': properties}

    with fiona.collection(shpname, "w", "ESRI Shapefile", schema) as output:
        for i in df.index:
            X = df.iloc[i][Xname]
            Y = df.iloc[i][Yname]
            point = Point(X, Y)
            props = dict(zip(df.columns, df.iloc[i]))
            output.write({'properties': props,
                          'geometry': mapping(point)})
    shutil.copyfile(prj, "{}.prj".format(shpname[:-4]))

def csv2points(csv, X='POINT_X', Y='POINT_Y', shpname=None, prj='EPSG:4326'):
    '''
    convert csv with point information to shapefile
    '''
    if not shpname:
        shpname = csv[:-4] + '.shp'
    df = pd.read_csv(csv)
    df['geometry'] = [Point(p) for p in zip(df[X], df[Y])]
    df2shp(df, shpname, geo_column='geometry', prj=prj)

def xlsx2points(xlsx, sheetname='Sheet1', X='X', Y='Y', shpname=None, prj='EPSG:4326'):
    '''
    convert Excel file with point information to shapefile
    '''
    if not shpname:
        shpname = xlsx.split('.')[0] + '.shp'
    df = pd.read_excel(xlsx, sheetname)
    df['geometry'] = [Point(p) for p in zip(df[X], df[Y])]
    df2shp(df, shpname, geo_column='geometry', prj=prj)


def df2shp(df, shpname, geo_column='geometry', prj=None):
    '''
    like above, but requires a column of shapely geometry information
    '''
    # enforce character limit for names! (otherwise fiona marks it zero)
    # somewhat kludgey, but should work for duplicates up to 99
    df.columns = map(str, df.columns) # convert columns to strings in case some are ints
    overtheline = [(i, '{}{}'.format(c[:8],i)) for i, c in enumerate(df.columns) if len(c) > 10]

    newcolumns = list(df.columns)
    for i, c in overtheline:
        newcolumns[i] = c
    df.columns = newcolumns
    
    print 'writing {}...'.format(shpname)
    properties = shp_properties(df)
    del properties[geo_column]
    
    # sort the dataframe columns (so that properties coincide)
    df = df.sort(axis=1)

    Type = df.iloc[0][geo_column].type
    schema = {'geometry': Type, 'properties': properties}
    knt = 0
    length = len(df)
    problem_cols = []
    with fiona.collection(shpname, "w", "ESRI Shapefile", schema) as output:
        for i in range(length):
            geo = df.iloc[i][geo_column]

            # convert numpy ints to python ints (tedious!)
            props = {}
            for c in range(len(df.columns)):
                value = df.iloc[i][c]
                col = df.columns[c]
                #print i,c,col,value
                dtype = df[col].dtype.name
                #dtype = df.iloc[c].dtype.name
                if col == geo_column:
                    continue
                else:
                    try:
                        if 'int' in dtype:
                            props[col] = int(value)
                        #if 'float' in dtype:
                            #props[col] = np.float64(value)
                        if schema['properties'][col] == 'str' and dtype == 'object':
                            props[col] = str(value)
                        else:
                            props[col] = value
                    except AttributeError: # if field is 'NoneType'
                        problem_cols.append(col)
                        props[col] = ''
            
            output.write({'properties': props,
                          'geometry': mapping(geo)})
            knt +=1
            print '\r{:d}%'.format(100*knt/length),
    if prj:
        if 'epsg' in prj.lower():
            epsg = int(prj.split(':')[1])
            prjstr = getPRJwkt(epsg).replace('\n', '') # get rid of any EOL
            ofp = open("{}.prj".format(shpname[:-4]), 'w')
            ofp.write(prjstr)
            ofp.close()
        else:
            try:
                shutil.copyfile(prj, "{}.prj".format(shpname[:-4]))
            except IOError:
                print 'Warning: could not find specified prj file. shp will not be projected.'

    if len(problem_cols) > 0:
        print 'Warning: Had problems writing these DataFrame columns: {}'.format(problem_cols)
        print 'Check their dtypes.'




def linestring_shpfromdf(df, shpname, IDname, Xname, Yname, Zname, prj, aggregate=None):
    '''
    creates point shape file from pandas dataframe
    shp: name of shapefile to write
    Xname: name of column containing Xcoordinates
    Yname: name of column containing Ycoordinates
    Zname: name of column containing Zcoordinates
    IDname: column with unique integers for each line
    aggregate = dict of column names (keys) and operations (entries)
    '''

    # setup properties for schema
    # if including other properties besides line identifier,
    # aggregate those to single value for line, using supplied aggregate dictionary
    if aggregate:
        cols = [IDname] + aggregate.keys()
        aggregated = df[cols].groupby(IDname).agg(aggregate)
        aggregated[IDname] = aggregated.index
        properties = shp_properties(aggregated)
    # otherwise setup properties to just include line identifier
    else:
        properties = {IDname: 'int'}
        aggregated = pd.DataFrame(df[IDname].astype('int32'))

    schema = {'geometry': '3D LineString', 'properties': properties}
    lines = list(np.unique(df[IDname].astype('int32')))

    with fiona.collection(shpname, "w", "ESRI Shapefile", schema) as output:
        for line in lines:

            lineinfo = df[df[IDname] == line]
            vertices = lineinfo[[Xname, Yname, Zname]].values
            linestring = asLineString(vertices)
            props = dict(zip(aggregated.columns, aggregated.ix[line, :]))
            output.write({'properties': props,
                          'geometry': mapping(linestring)})
    shutil.copyfile(prj, "{}.prj".format(shpname[:-4]))
    
    
def read_raster(rasterfile):
    '''
    reads a GDAL raster into numpy array for plotting
    also returns meshgrid of x and y coordinates of each cell for plotting
    based on code stolen from:
    http://stackoverflow.com/questions/20488765/plot-gdal-raster-using-matplotlib-basemap 
    '''
    try:
        ds = gdal.Open(rasterfile)
    except:
        raise IOError("problem reading raster file {}".format(rasterfile))

    print '\nreading in {} into numpy array...'.format(rasterfile)
    data = ds.ReadAsArray()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    
    xres = gt[1]
    yres = gt[5]
    
    # get the edge coordinates and add half the resolution 
    # to go to center coordinates
    xmin = gt[0] + xres * 0.5
    xmax = gt[0] + (xres * ds.RasterXSize) - xres * 0.5
    ymin = gt[3] + (yres * ds.RasterYSize) + yres * 0.5
    ymax = gt[3] + yres * 0.5
    
    del ds

    print 'creating a grid of xy coordinates in the original projection...'
    xy = np.mgrid[xmin:xmax+xres:xres, ymax+yres:ymin:yres]
    
    # create a mask for no-data values
    data[data<-1.0e+20] = 0
    
    return data, gt, proj, xy
    
def flatten_3Dshp(shp, outshape=None):
	
	if not outshape:
	    outshape = '{}_2D.shp'.format(shp[:-4])	
	
	df = shp2df(shp, geometry=True)
	
	# somehow this removes 3D formatting
	df['2D'] = df['geometry'].map(lambda x: loads(x.wkt))
	
	# drop the original geometry column
	df = df.drop('geometry', axis=1)
	
	# poop it back out
	df2shp(df, outshape, '2D', shp[:-4]+'.prj')
	

	
	