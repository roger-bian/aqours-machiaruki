import os

os.environ['OGR_SKIP'] = 'LIBKML'

from dash import Dash, dcc, html, Input, Output, State, no_update, Patch
import plotly.express as px
import pandas as pd
import geotable
import geocoder
import requests
import hashlib
import mimetypes
import re


KML_URL = 'https://www.google.com/maps/d/u/0/kml?forcekml=1&mid=1hQhJDhsE87Iu9BJOln-EnveGbow&lid=Cs8qfjzbvoQ'
KML_PATH = os.path.join('assets', 'machiaruki.kml')
IMG_DIR = os.path.join('assets', 'img')


def fetch_kml(path=KML_PATH, url=KML_URL):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        response = requests.get(url)
        response.raise_for_status()
        with open(path, 'wb') as f:
            f.write(response.content)
    return path


def cache_images(urls):
    # Google's hosted-image CDN (mymaps.usercontent.google.com) blocks/rate-limits
    # these requests when made from a browser tab, so images are downloaded once
    # server-side and served locally via Dash's assets/ static folder instead
    os.makedirs(IMG_DIR, exist_ok=True)
    cached = {name.split('.')[0]: name for name in os.listdir(IMG_DIR)}

    paths = []
    for url in urls:
        digest = hashlib.sha1(url.encode()).hexdigest()
        filename = cached.get(digest)
        if filename is None:
            response = requests.get(url)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
            ext = mimetypes.guess_extension(content_type) or '.jpg'
            filename = digest + ext
            with open(os.path.join(IMG_DIR, filename), 'wb') as f:
                f.write(response.content)
            cached[digest] = filename
        paths.append(f'/assets/img/{filename}')
    return paths


# labels are not always all present in a given entry's Description (e.g. some
# newer entries have no member or business-hours label), so fields are located
# by position rather than assumed to sit adjacent to a fixed set of neighbors
FIELD_LABELS = ['メンバー／', '住所／', '営業時間／', '定休日／']


def _parse_description(text):
    hits = sorted((text.find(label), label) for label in FIELD_LABELS if label in text)
    fields = {}
    for i, (pos, label) in enumerate(hits):
        start = pos + len(label)
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        fields[label] = re.sub('(<br>)+$', '', text[start:end]).strip()

    hours = fields.get('営業時間／', '')\
        .replace('　', '')\
        .replace('：', ':')\
        .replace('~', '～').replace(' ～ ', '～')\
        .replace('<br>', ' ')

    holidays = fields.get('定休日／', '').split('<br>')[0].strip() or 'なし'

    return {
        'member': fields.get('メンバー／', ''),
        'address': fields.get('住所／', '').replace('<br>', ' ').strip(),
        'hours': hours,
        'holidays': holidays,
    }


def df_clean(df):
    # drop unused columns
    df = df.drop(columns=['geometry_layer', 'geometry_proj4'])

    # find img link and cache it locally
    df['img'] = df['Description']\
        .apply(lambda x: re.findall('<img src="(.*)" height', x)[0])\
        .str.strip()
    df['img'] = cache_images(df['img'])

    # find member/address/hours/holidays
    parsed = pd.DataFrame(df['Description'].apply(_parse_description).tolist(), index=df.index)
    df = pd.concat([df, parsed], axis=1)

    # remove Description
    df = df.drop(columns=['Description'])

    return df


t = geotable.load(fetch_kml())
t_clean = df_clean(t)


MEMBER_COLORS = {
    '高海千歌': '#F0A20B',
    '桜内梨子': '#E9A9E8',
    '松浦果南': '#13E8AE',
    '黒澤ダイヤ': '#F23B4C',
    '渡辺曜': '#49B9F9',
    '津島善子': '#898989',
    '国木田花丸': '#E6D617',
    '小原鞠莉': '#AE58EB',
    '黒澤ルビィ': '#FB75E4'
}

# preview-only in-memory tracker for collected stamps/badges - resets on
# server restart; will be replaced by real DB reads/writes once one exists.
# marker color reflects how many of the two flags are collected (0/1/2)
DEFAULT_MARKER_COLOR = '#636efa'
ONE_COLLECTED_COLOR = '#f39c12'
BOTH_COLLECTED_COLOR = '#2ecc71'
DEFAULT_MARKER_SIZE = 36

collection_state = {i: {'stamp': False, 'badge': False} for i in range(len(t_clean))}

ALL_LATS = t_clean.geometry_object.apply(lambda x: x.y).tolist()
ALL_LONS = t_clean.geometry_object.apply(lambda x: x.x).tolist()


def _color_for(i):
    collected_count = sum(collection_state[i].values())
    if collected_count == 2:
        return BOTH_COLLECTED_COLOR
    if collected_count == 1:
        return ONE_COLLECTED_COLOR
    return DEFAULT_MARKER_COLOR


def _visible_indices(active_filters):
    active = set(active_filters or [])
    if not active:
        return list(range(len(t_clean)))
    indices = []
    for i in range(len(t_clean)):
        state = collection_state[i]
        stamp_match = 'stamp_missing' in active and not state['stamp']
        badge_match = 'badge_missing' in active and not state['badge']
        if stamp_match or badge_match:
            indices.append(i)
    return indices


fig = px.scatter_mapbox(
    t_clean,
    lat=ALL_LATS,
    lon=ALL_LONS,
    text=[str(i + 1) for i in range(len(t_clean))],
    opacity=0.7,
    zoom=10,
    mapbox_style='open-street-map'
    )
fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), uirevision='constant')
fig.update_traces(marker=dict(size=DEFAULT_MARKER_SIZE, color=DEFAULT_MARKER_COLOR),
                  textposition='middle center',
                  textfont=dict(color='white', size=16),
                  selector=dict(mode='markers+text'))


g = geocoder.ip('me')
fig.add_scattermapbox(
    lat=[g.latlng[0]],
    lon=[g.latlng[1]],
    showlegend=False,
    marker={'size': 12},
    opacity=0.8
)

# turn off native plotly.js hover effects - make sure to use
# hoverinfo="none" rather than "skip" which also halts events.
fig.update_traces(hoverinfo="none", hovertemplate=None)



# the panel is a plain fixed-position div (not dcc.Tooltip) so it can be
# centered in the viewport regardless of where the tapped point is - this
# also matters on mobile, where there's no hover to anchor a tooltip to
PANEL_BASE_STYLE = {
    'display': 'none',
    'position': 'fixed',
    'top': '50%',
    'left': '50%',
    'transform': 'translate(-50%, -50%)',
    'z-index': '1000',
    'background-color': 'white',
    'width': '300px',
    'max-width': '90vw',
    'max-height': '85vh',
    'overflow-y': 'auto',
    'box-shadow': '0 4px 20px rgba(0, 0, 0, 0.3)',
    'border-radius': '8px',
    'padding': '16px',
    'white-space': 'normal',
    'text-align': 'center',
}


def _panel_style(visible):
    return {**PANEL_BASE_STYLE, 'display': 'block' if visible else 'none'}


# invisible full-screen layer behind the panel but above the map - tapping
# anywhere outside the panel (including on another marker) hits this and
# closes the panel, since Plotly has no click event for "empty map area"
# to key off of directly
BACKDROP_STYLE = {
    'display': 'none',
    'position': 'fixed',
    'top': '0',
    'left': '0',
    'right': '0',
    'bottom': '0',
    'z-index': '999',
    'background-color': 'rgba(0, 0, 0, 0.2)',
}


def _backdrop_style(visible):
    return {**BACKDROP_STYLE, 'display': 'block' if visible else 'none'}


# small always-on floating control, separate from the tap-to-pin panel -
# filters which markers are drawn rather than opening/closing anything
FILTER_PANEL_STYLE = {
    'position': 'fixed',
    'top': '10px',
    'left': '10px',
    'z-index': '900',
    'background-color': 'white',
    'padding': '8px 12px',
    'border-radius': '8px',
    'box-shadow': '0 2px 8px rgba(0, 0, 0, 0.3)',
    'font-size': '14px',
}


# the panel's checklist/close-button ids only exist once its children are
# rendered by a callback, not in this initial static layout
app = Dash(__name__, suppress_callback_exceptions=True)

app.layout = html.Div([
    dcc.Graph(
        id="graph-basic-2",
        figure=fig,
        config={'scrollZoom': True},
        style={'height': '100vh', 'width': '100vw'},
    ),
    html.Div(
        dcc.Checklist(
            id='filter-controls',
            options=[
                {'label': 'スタンプ（未獲得）', 'value': 'stamp_missing'},
                {'label': '缶バッジ（未獲得）', 'value': 'badge_missing'},
            ],
            value=[],
        ),
        style=FILTER_PANEL_STYLE,
    ),
    html.Div(id="panel-backdrop", n_clicks=0, style=_backdrop_style(False)),
    html.Div(id="detail-panel", style=_panel_style(False)),
    dcc.Store(id="selected-point"),
    dcc.Store(id="visible-indices", data=list(range(len(t_clean)))),
], style={'margin': 0, 'padding': 0})


def _build_info_children(num):
    t_row = t_clean.iloc[num]
    img_src = t_row['img']
    name = t_row['Name']
    member = t_row['member']

    address = t_row['address']
    address_r = [html.B('[住所]'), html.Br()]
    for i in address.split():
        address_r.append(i)
        address_r.append(html.Br())

    hours = t_row['hours']
    hours_r = [html.B('[営業時間]'), html.Br()]
    for i in hours.split():
        hours_r.append(i)
        hours_r.append(html.Br())

    holidays = t_row['holidays']
    holidays_r = [html.B('[定休日]'), html.Br()]
    for i in holidays.split():
        holidays_r.append(i)
        holidays_r.append(html.Br())

    return [
        html.Img(src=img_src, style={"width": "100%"}),
        *([html.P(member, style={"color": MEMBER_COLORS.get(member, "black"), "margin-bottom": "0"})] if member else []),
        html.H3(html.B(name), style={"color": "darkblue", "overflow-wrap": "break-word", "margin-top": "0"}),
        html.P(address_r),
        html.P(hours_r),
        html.P(holidays_r),
    ]


@app.callback(
    Output("detail-panel", "style"),
    Output("detail-panel", "children"),
    Output("selected-point", "data"),
    Output("panel-backdrop", "style"),
    Input("graph-basic-2", "clickData"),
    State("visible-indices", "data"),
)
def display_click(clickData, visible_indices):
    if clickData is None:
        return no_update, no_update, no_update, no_update

    pt = clickData["points"][0]

    # don't pin the panel for taps on the current location marker
    if [pt['lat'], pt['lon']] == g.latlng:
        return no_update, no_update, no_update, no_update

    # pointNumber is a position within the currently-filtered trace, not the
    # original row index - map it back via the indices that were drawn
    num = visible_indices[pt["pointNumber"]]

    children = [
        html.Button('✕', id='close-panel', n_clicks=0, style={
            'float': 'right', 'border': 'none', 'background': 'none',
            'font-size': '16px', 'cursor': 'pointer',
        }),
        *_build_info_children(num),
        dcc.Checklist(
            id='collection-checklist',
            options=[
                {'label': 'スタンプ', 'value': 'stamp'},
                {'label': '缶バッジ', 'value': 'badge'},
            ],
            value=[key for key, collected in collection_state[num].items() if collected],
            style={'margin-top': '10px'},
        ),
    ]

    return _panel_style(True), children, num, _backdrop_style(True)


@app.callback(
    Output("graph-basic-2", "figure"),
    Output("visible-indices", "data", allow_duplicate=True),
    Input("collection-checklist", "value"),
    State("selected-point", "data"),
    State("filter-controls", "value"),
    prevent_initial_call=True,
)
def toggle_collection(value, num, active_filters):
    if num is None:
        return no_update, no_update

    new_state = {'stamp': 'stamp' in value, 'badge': 'badge' in value}
    # the checklist also fires this callback once when it's first mounted
    # (seeded with the point's existing state), despite prevent_initial_call -
    # skip the no-op so opening a panel doesn't push a pointless update
    if new_state == collection_state[num]:
        return no_update, no_update
    collection_state[num] = new_state

    # rebuild the currently-drawn points from scratch (not just recolor) -
    # toggling a flag can make this point start/stop matching an active
    # filter, so it may need to appear or disappear, not just change color.
    # patch only these arrays in place, rather than sending back the whole
    # figure - a full figure replacement re-sends the mapbox center/zoom
    # baked in at server startup, which was resetting the user's current
    # pan/zoom on every toggle regardless of uirevision
    indices = _visible_indices(active_filters)
    patch = Patch()
    patch['data'][0]['lat'] = [ALL_LATS[i] for i in indices]
    patch['data'][0]['lon'] = [ALL_LONS[i] for i in indices]
    patch['data'][0]['text'] = [str(i + 1) for i in indices]
    patch['data'][0]['marker']['color'] = [_color_for(i) for i in indices]
    return patch, indices


@app.callback(
    Output("graph-basic-2", "figure", allow_duplicate=True),
    Output("visible-indices", "data", allow_duplicate=True),
    Input("filter-controls", "value"),
    prevent_initial_call=True,
)
def apply_filters(active_filters):
    indices = _visible_indices(active_filters)
    patch = Patch()
    patch['data'][0]['lat'] = [ALL_LATS[i] for i in indices]
    patch['data'][0]['lon'] = [ALL_LONS[i] for i in indices]
    patch['data'][0]['text'] = [str(i + 1) for i in indices]
    patch['data'][0]['marker']['color'] = [_color_for(i) for i in indices]
    return patch, indices


@app.callback(
    Output("detail-panel", "style", allow_duplicate=True),
    Output("panel-backdrop", "style", allow_duplicate=True),
    Input("close-panel", "n_clicks"),
    prevent_initial_call=True,
)
def close_panel(n_clicks):
    # the button is newly mounted each time the panel opens (it lives inside
    # detail-panel's dynamically-rendered children), so this callback also
    # fires once with the initial n_clicks=0 despite prevent_initial_call -
    # only a real click (n_clicks > 0) should actually close the panel
    if not n_clicks:
        return no_update, no_update
    return _panel_style(False), _backdrop_style(False)


@app.callback(
    Output("detail-panel", "style", allow_duplicate=True),
    Output("panel-backdrop", "style", allow_duplicate=True),
    Input("panel-backdrop", "n_clicks"),
    prevent_initial_call=True,
)
def close_via_backdrop(n_clicks):
    if not n_clicks:
        return no_update, no_update
    return _panel_style(False), _backdrop_style(False)


if __name__ == "__main__":
    app.run(debug=True)
