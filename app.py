import datetime
import io

from chalice import Chalice, Response
from geopy.distance import geodesic
import gpxpy
import matplotlib.pyplot as plt

app = Chalice(app_name='gpx-lambda')


@app.route('/gpx/summary', methods=['POST'], content_types=['application/xml'])
def gpx_summary():
    """
    Compute global and per-track summaries of tracks in a GPX file.
    :return: summary dict with global and per-track metrics
    """
    request = app.current_request

    # TODO error handling
    # Just assume utf-8 :/
    gpx = gpxpy.parse(request.raw_body.decode('utf-8'))

    # TODO query params
    # m/s threshold for calculating moving time
    movement_threshold_m_per_sec = 0.5
    # point sampling rate for calculating elevation gain, to smooth jitter
    elev_sample_seconds = 3

    elev_sample_delta = datetime.timedelta(seconds=elev_sample_seconds)
    summary = {
        'total_distance': 0,
        'total_elapsed_seconds': 0,
        'total_moving_seconds': 0,
        'total_elevation': 0,
        'tracks': [],
    }

    for track in gpx.tracks:
        t_summary = {
            'distance': 0,
            'elapsed_seconds': 0,
            'moving_seconds': 0,
            'elevation': 0,
        }
        start_time = None
        end_time = None

        for segment in track.segments:
            last_point = None
            last_elev_point = None

            for point in segment.points:
                if start_time is None or point.time < start_time:
                    start_time = point.time
                if end_time is None or point.time > end_time:
                    end_time = point.time
                if last_point is not None:
                    # Use ellipsoid model of Earth for distance calculation
                    distance = geodesic(
                        (point.latitude, point.longitude),
                        (last_point.latitude, last_point.longitude),
                    )
                    t_summary['distance'] += distance.meters

                    # Only count toward moving_seconds if over movement threshold
                    seconds_delta = (point.time - last_point.time).seconds
                    t_summary['elapsed_seconds'] += seconds_delta
                    if distance.meters / seconds_delta > movement_threshold_m_per_sec:
                        t_summary['moving_seconds'] += seconds_delta

                    # Elevation data is sampled to mitigate jitter
                    if last_elev_point is None:
                        last_elev_point = point
                    elif point.time - last_elev_point.time > elev_sample_delta:
                        if point.elevation > last_elev_point.elevation:
                            elev_diff = point.elevation - last_point.elevation
                            t_summary['elevation'] += elev_diff
                        last_elev_point = point
                last_point = point

        for field in ['distance', 'elevation']:
            t_summary[field] = round(t_summary[field], 2)

        summary['total_distance'] += t_summary['distance']
        summary['total_elapsed_seconds'] += t_summary['elapsed_seconds']
        summary['total_moving_seconds'] += t_summary['moving_seconds']
        summary['total_elevation'] += t_summary['elevation']
        summary['tracks'].append(t_summary)

    for field in ['total_distance', 'total_elevation']:
        summary[field] = round(summary[field], 2)

    return summary


@app.route('/gpx/plot', methods=['POST'], content_types=['application/xml'])
def gpx_plot():
    """
    Plot GPX tracks as a static image (PNG).
    :return: PNG image byte sequence
    """
    request = app.current_request

    # TODO error handling
    # Just assume utf-8 :/
    gpx = gpxpy.parse(request.raw_body.decode('utf-8'))

    lat = []
    lon = []

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                lat.append(point.latitude)
                lon.append(point.longitude)

    fig = plt.figure()
    ax = plt.Axes(fig, [0., 0., 1., 1.], )
    ax.set_aspect('equal')
    ax.set_axis_off()
    fig.add_axes(ax)
    plt.plot(lon, lat, color='deepskyblue', lw=0.5, alpha=0.8)
    buf = io.BytesIO()
    plt.savefig(buf, facecolor='black', format='png')
    buf.seek(0)
    return Response(body=buf.read(), headers={'Content-Type': 'image/png'})
