##########################IMPORTS########################
#For timing script
import datetime
#For file IO/data Handling
import os
import cPickle as pickle
#import pandas as pd
#Linear Algebra library
import numpy as np
from scipy.spatial import  cKDTree
#Plotting Imports and configuration
import matplotlib.pyplot as plt
from shapely.geometry import LineString,Polygon
from descartes.patch import PolygonPatch
#Importing custom classes and function
from sq_Cells import sq_Cells


#################Global Variables#######################
dtype=np.float64            #data type of any numpy array created
sq_cells_basepath='sq_cells_data/'
if not os.path.exists(sq_cells_basepath):
    os.makedirs(sq_cells_basepath)

#################Function Definition####################
def linear_interpolate_hex_to_square(hex_cells_dict,layer,resolution=(500,500)):
    '''
    DESCRIPTION:
        This function will interpolate the energy deposit in hexagonal cells
    from the input file to a energy deposit in the equivalent square grid
    Here we will interpolate according the area of overlap of a cell with
    the cells of square grid.

    INPUT:
        hex_cells_dict: the dictionary of input geometry read from root file
        resolution  :(int,int) the resolution of the square grid (TUPLE)
        layer       :(int) the layer id
    OUTPUT:
        coef    : a dictionary which contains the coefficient of overlap for
                each cells with corresponding sqare cell and fraction
                stored as:
                {
                    hexid :[((i,j),cf),((i,j),cf)....]
                }
    '''
    cells_dict=hex_cells_dict
    t1=datetime.datetime.now()

    #Creating the empty energy map (initialized with zeros)
    #coef=np.zeros(resolution,dtype=dtype)

    #Iterating over all the cells to get the bounds of the detector
    print '>>> Calculating Bounds'
    center_x=map(lambda c:c.center.x,cells_dict.values())
    max_x=max(center_x)
    min_x=min(center_x)
    center_y=map(lambda c:c.center.y,cells_dict.values())
    max_y=max(center_y)
    min_y=min(center_y)
    t2=datetime.datetime.now()
    print 'Bounding completed in: ',t2-t1,' sec\n'

    #Calculating the maximum length of any cells
        #(will to used to specify search radius in KD tree)
    print '>>> Calculating the search radius'
    max_length_hex=max(map(
                    lambda c: max([
                    c.vertices.bounds[2]-c.vertices.bounds[0],
                    c.vertices.bounds[3]-c.vertices.bounds[1]
                    ]),cells_dict.values())
                    )
    #DISCUSS and CONFIRM THIS LINE
    max_length_sq=np.sqrt( ((max_x-min_x)/(resolution[0]-1))**2+
                           ((max_y-min_y)/(resolution[1]-1))**2 )
    #Any overlapping cells will be in this search radius
    search_radius=(max_length_hex/2)+(max_length_sq/2)
    t3=datetime.datetime.now()
    print 'Search Radius finding completed in: ',t3-t2,' sec\n'

    #Getting the square cells mesh (dict) for overlap calculation
    print '>>> Generating the square mesh grid'
    sq_cells_dict=get_square_cells(layer,resolution,min_x,min_y,max_x,max_y)
    t4=datetime.datetime.now()
    print 'Generating Mesh Grid completed in: ',t4-t3,' sec\n'

    #Calculating the coefficient of overlap
    #(currently in for of ditionary)
    print '>>> Calculating the overlap coefficient'
    coef=calculate_overlap(cells_dict.values(),sq_cells_dict.values(),
                            search_radius,min_overlap_area=0.0)
    t5=datetime.datetime.now()
    print 'Overlap Coef Finding completed in: ',t5-t4,' sec\n'

    #Now change it if we want the overlap with sq cells
    #in form of array
    #print coef
    return coef

def get_square_cells(layer,resolution,min_x,min_y,max_x,max_y):
    '''
    DESCRIPTION:
        This function will generate square mesh grid by Creating
    the square polygon. This function create the square cell using the
    class defined in sq_Cells.py script. This first calculate the appropriate
    length of the square cells based on the resolution i.e total number of
    cells in each direction and distance available.
    USAGE:
        INPUT:
            layer   : layer number will be used to save the square grid for
                        that layer in the folder automatically created with
                        name 'sq_cells_data' in current working directory.
            resolution: the number of cells in both x and y direction in form of
                        tuple (res_x,res_y)
            min_x   : the lower bound of x in whole detector geometry to start
                        creation of square cells from there.
            min_y   : the minimum bound of y in whole detector geometry.
            max_x   : the max bound of x coordinate in whole detector.
            max_y   : the maximum bound of y in whole detector.
        OUPUT:
            sq_cells: a dictionary with the key as id of cell and
                        value as the square cell object.
                        {
                        key:(i,j) : value:(sqCell object)
                        }
            This dictionary is saved as pickle file in a new directory created
            automatically in current directory named as 'sq_cells_data'
    '''
    #Finding the dimension of each cells
    x_length=(max_x-min_x)/(resolution[0]-1) #n-1 is used like in linear density
    y_length=(max_y-min_y)/(resolution[1]-1)

    #Creating empty array to store
    #sq_cells=np.empty(resolution,dtype=np.object)
    sq_cells={}

    #Time Comlexity = O(res[0]*res[1])
    for i in range(resolution[0]):
        for j in range(resolution[1]):
            #Center of the square polygon
            center=(min_x+i*x_length,min_y+j*y_length)
            id=(i,j)    #given in usual matrix notation
            sq_cells[id]=sq_Cells(id,center,x_length,y_length)

    #Saving the sq_cell sq_cell_data in given folder
    sq_cells_filename=sq_cells_basepath+'sq_cells_dict_layer_%s_res_%s.pkl'%(layer,resolution[0])
    fhandle=open(sq_cells_filename,'wb')
    pickle.dump(sq_cells,fhandle,protocol=pickle.HIGHEST_PROTOCOL)
    fhandle.close()
    return sq_cells

def calculate_overlap(hex_cells_list,sq_cells_list,search_radius,min_overlap_area=0.0):
    '''
    DESCRIPTION:
        This function calculate the overlap coeffieicnt from between the
        hexagonal cell and corresponding square cells. It is called internally
        by above linear_interpolate_hex_to_square frunciton.

        Generated a coefficient dictionary of form:
        { hexagon id 1: [(overlap_sq_cell_id,overlap_coefficient),(....),(.....)]
        }
    INPUT:
        hex_cells_list  : hexagonal cells in form of list
        sq_cells_list   : square cells in form of list
        search_radius   : upto what distance to search in KD-Tree.
        min_overlap_area: the minimum overlap with square cell to accept it
                            as candidate of overlap_cells
                            (default greater than 0.0)
    OUTPUT:
        coef_dict       : the dictionary containg the mapping of hexagonal cells
                            with the overlapping square cells and their
                            coefficient of overlap in form of fraction of area.
    '''
    hex_centers=np.array([cell.center.coords[0]
                            for cell in hex_cells_list])
    sq_centers=np.array([cell.center.coords[0]
                            for cell in sq_cells_list])

    hex_kd_tree=cKDTree(hex_centers)
    sq_kd_tree=cKDTree(sq_centers)

    #Calculating all the possible overlaps of each hex cells
    #with all the sq cells
    overlap_candidate_id=hex_kd_tree.query_ball_tree(
                                    sq_kd_tree,search_radius)
    coef_dict={}
    for i,sq_cell_id in enumerate(overlap_candidate_id):
        #Going one by one for each cell and seiving through
        #all its overlap
        hex_cell=hex_cells_list[i]
        overlap_candidates=[sq_cells_list[j] for j in sq_cell_id]
        overlap_area=[]
        for overlap_candidate in overlap_candidates:
            overlap=hex_cell.vertices.intersection(
                        overlap_candidate.polygon)
            overlap_area.append(overlap.area)

        #Filtering the ones accoding to minimum ovelap criteria
        #by default the zero overlap cells are discarded
        sq_cell_id=np.array(sq_cell_id)
        overlap_area=np.array(overlap_area)
        selected_indices=overlap_area>min_overlap_area

        #Final accumulation of selected cell and their overlap area
        sq_cell_id_final=sq_cell_id[selected_indices]
        overlap_area_final=overlap_area[selected_indices]
        overlap_coef_final=overlap_area_final/np.sum(overlap_area_final)

        coef_dict[hex_cell.id]=[]
        for fid,coef in zip(sq_cell_id_final,overlap_coef_final):
            coef_dict[hex_cell.id].append((sq_cells_list[fid].id,coef))

    return coef_dict

def plot_sq_cells(cell_d):
    '''
    DESCRIPTION:
        This function is to visualize the correctness of the
        generated square grid from the Square Ploygon generated by
        get_square_cells function above.
    USAGE:
        INPUT:
            cell_d  : this takes in the square cell dictionary generated
                        by the get_square_cells function above.
        OUTPUT:
            No outputs currently

    '''
    t0=datetime.datetime.now()
    fig=plt.figure()
    ax1=fig.add_subplot(111)
    for id,cell in sq_cells_dict.items():
        poly=cell.polygon
        patch=PolygonPatch(poly,alpha=0.5,zorder=2,edgecolor='blue')
        ax1.add_patch(patch)
    t1=datetime.datetime.now()
    print '>>> Plot Completed in: ',t1-t0,' sec'
    ax1.set_xlim(-160, 160)
    ax1.set_ylim(-160, 160)
    ax1.set_aspect(1)
    plt.show()

def plot_hex_to_square_map(coef,hex_cells_dict,sq_cells_dict):
    '''
    DESCRIPTION:
        This function is for visualization of mapping of Hexagonal cells
        to the square cells, for checking the correctness of resolution
        of interpolation with the criteria as mentioned by Florian Sir,
        (one square cell not overlapping with more than three hexagon cells)
    USAGE:
        This function is called internally in main.py generate_interpolation
        function.
        INPUT:
            coef : the coef dictionary mapping each hexagonal cells to their
                    correspoinding square cells
            hex_cells_dict  : the dictionary of hexagonal cells obtained from
                                the root file
            sq_cells_dict   : the square cell dictionary generated by
                                get_square_cells function above and saved in
                                'sq_cells_data' directory in current location
        OUTPUT:
            Currently no output from this function
    '''
    t0=datetime.datetime.now()
    # fig=plt.figure()
    # ax1=fig.add_subplot(111)
    print '>>> Calculating the area of smallar cell for filtering'
    filter_hex_cells=([c.vertices.area for c in hex_cells_dict.values()
                        if len(list(c.vertices.exterior.coords))==7])
    small_wafer_area=min(filter_hex_cells)
    t1=datetime.datetime.now()
    print '>>> Area calculated %s in time: %s sec'%(
                                    small_wafer_area,t1-t0)
    t0=t1

    for hex_id,sq_overlaps in coef.items():
        hex_cell=hex_cells_dict[hex_id]
        poly=hex_cell.vertices
        #Filtering the cells in smaller region
        if poly.area!=small_wafer_area:
            continue

        fig=plt.figure()
        ax1=fig.add_subplot(111)
        x,y=poly.exterior.xy
        ax1.plot(x,y,'o',zorder=1)
        patch=PolygonPatch(poly,alpha=0.5,zorder=2,edgecolor='blue')
        ax1.add_patch(patch)
        print '>>> Plotting hex cell: ',hex_id
        for sq_cell_data in sq_overlaps:
            sq_cell_id=sq_cell_data[0]
            overlap_coef=sq_cell_data[1]
            sq_cell=sq_cells_dict[sq_cell_id]
            print ('overlapping with sq_cell: ',sq_cell_id,
                                    'with overlap coef: ',overlap_coef)
            poly=sq_cell.polygon
            x,y=poly.exterior.xy
            ax1.plot(x,y,'o',zorder=1)
            patch=PolygonPatch(poly,alpha=0.5,zorder=2,edgecolor='red')
            ax1.add_patch(patch)
        t1=datetime.datetime.now()
        print 'one hex cell overlap complete in: ',t1-t0,' sec\n'
        t0=t1
        #ax1.set_xlim(-160, 160)
        #ax1.set_ylim(-160, 160)
        #ax1.set_aspect(1)
        plt.show()
