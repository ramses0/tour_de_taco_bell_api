import os
import math
import googlemaps

from models import Request, Result
from errors import PathFinderError

# allowed difference between target distance and route distance
TOLERANCE = 5

# get api key from environ if present else set it

def get_client():
    key = os.getenv('GMAPS_KEY', 'YOUR_KEY_HERE')
    return googlemaps.Client(key)

def _distance(p1, p2):
    return math.sqrt(
        (p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2
    )

def lat_lon_from_tbell(tbell):
    """
    Returns a taco bell's (lat, lng) tuple from the json object.
    Used in sorting things.
    """

    return (tbell['geometry']['location']['lat'],
            tbell['geometry']['location']['lng'])

def haversine_distance(p1, p2):
    """
    Points must be in (lon, lat) coordinates and must start in degrees.
    Haversine formula taken from here:
    http://www.movable-type.co.uk/scripts/latlong.html
    """

    mean_radius_of_earth = 3959 # miles
    p1r = (math.radians(p1[0]), math.radians(p1[1]))
    p2r = (math.radians(p2[0]), math.radians(p2[1]))
    a = (
        math.sin((p1r[0] - p2r[0]) / 2.) ** 2 +
        math.cos(p1r[0]) * math.cos(p2r[0]) *
        math.sin((p1r[1] - p2r[1]) / 2.) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return c * mean_radius_of_earth


def tbell_finder(start_lat_lon, client):
    """
    Returns a list of Taco Bells in a certain radius of the start address.
    Default value is 25 miles.
    """

    # 40233.6 is 25 miles in meters
    response = client.places("taco bell", location=start_lat_lon,
                             radius=40233.6)
    if response['status'] == 'OK':
        return response['results']
    else:
        return 'error -- %s' % response['status']

def nearest_tbell(start_lat_lon, tbell_list):
    lat_lons = [lat_lon_from_tbell(x) for x in tbell_list]
    distances = [
        _distance(start_lat_lon, x) for x in lat_lons
    ]
    min_index, _ = min(enumerate(distances), key=lambda p: p[1])
    return tbell_list[min_index]

def choose_next_tbell(home_lat_lon, start_lat_lon, tbell_list,
                      target_dist, cumul_dist):
    """
    Chooses from among the nearest taco bells not yet visited the next taco
    bell. Tries at each stage to minimize:

    abs( target - (cumulative + next leg + straight back from next) )

    In practice, this leads to preferring longer steps earlier, but not in
    directions that would lead to considerable overshooting on the way back.

    Note that we're not optimizing over bicycling distance here, just
    over distance on the surface of the earth. That's to keep API calls
    down and for speed (probably).
    """

    def pen(p):
        route_dist = (cumul_dist + haversine_distance(p, start_lat_lon) +
                      haversine_distance(p, home_lat_lon))
        return route_dist, abs(int(target_dist) - route_dist)


    closest_two_tbells = sorted(
        tbell_list,
        key=lambda x: haversine_distance(start_lat_lon, lat_lon_from_tbell(x))
    )[:2]

    pens = [(pen(lat_lon_from_tbell(x)), x) for x in closest_two_tbells]

    return sorted(pens, key=lambda x: x[0][1])[0]

def choose_tbell_sequence(home_lat_lon, tbell_list, target_dist):

    nearest = nearest_tbell(home_lat_lon, tbell_list)
    cur_lat_lon = lat_lon_from_tbell(nearest)
    tbell_list.pop(tbell_list.index(nearest))
    cumul_dist = haversine_distance(home_lat_lon, cur_lat_lon)
    pen = 100000

    # path will be a series of lat_lon tuples that will be sent
    # to the directions API as endpoints
    path = [home_lat_lon, lat_lon_from_tbell(nearest)]

    while pen > TOLERANCE:
        # don't want to choose more taco bells if we're already past target
        if cumul_dist > int(target_dist) or not tbell_list:
            break
        pen_tup, next_tbell = choose_next_tbell(
            home_lat_lon,
            cur_lat_lon,
            tbell_list,
            target_dist,
            cumul_dist
        )
        tbell_list.pop(tbell_list.index(next_tbell))
        cur_lat_lon = lat_lon_from_tbell(next_tbell)
        path.append(cur_lat_lon)
        cumul_dist, pen = pen_tup

    path.append(home_lat_lon)
    return path

def path_dict_to_embedded_query(path_dict):
    """
    Converts dict with 'path', 'status' keys into a url string that can be
    sent to the google maps embed API
    """

    key = os.getenv('GMAPS_KEY', 'YOUR_KEY_HERE')

    if path_dict['status'] != 'ok':
        raise PathFinderError('Failed to find path')
    base = (
        'https://www.google.com/maps/embed/v1/directions'
        '?key={KEY}'
        '&origin={ORIGIN}'
        '&destination={ORIGIN}'
        '&mode=bicycling'
        '&waypoints={WAYPOINTS}'
    )

    points = path_dict['path']
    origin = ','.join(map(str, points[0]))
    waypoints = '|'.join([','.join(map(str, p)) for p in points[1:-1]])

    return base.format(KEY=key, ORIGIN=origin, WAYPOINTS=waypoints)
