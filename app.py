import os

os.environ['OGR_SKIP'] = 'LIBKML'

from dash import Dash, dcc, html, Input, Output, no_update
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


fig = px.scatter_mapbox(
    t_clean,
    lat=t_clean.geometry_object.apply(lambda x: x.y),
    lon=t_clean.geometry_object.apply(lambda x: x.x),
    opacity=0.7,
    zoom=10,
    height=700,
    mapbox_style='open-street-map'
    )


g = geocoder.ip('me')
fig.add_scattermapbox(
    lat=[g.latlng[0]],
    lon=[g.latlng[1]],
    showlegend=False,
    marker={'size': 12},
    opacity=0.8
)


fig.update_traces(marker=dict(size=12),
                  selector=dict(mode='markers'))

# turn off native plotly.js hover effects - make sure to use
# hoverinfo="none" rather than "skip" which also halts events.
fig.update_traces(hoverinfo="none", hovertemplate=None)



app = Dash(__name__)

app.layout = html.Div([
    html.H1('沼津 まちあるき スタンプ 設置店舗', style={'text-align': 'center'}),
    dcc.Graph(id="graph-basic-2", figure=fig, clear_on_unhover=True, config={'scrollZoom': True}),
    dcc.Tooltip(id="graph-tooltip"),
])


@app.callback(
    Output("graph-tooltip", "show"),
    Output("graph-tooltip", "bbox"),
    Output("graph-tooltip", "children"),
    Input("graph-basic-2", "hoverData"),
)


def display_hover(hoverData):
    if hoverData is None:
        return False, no_update, no_update

    # demo only shows the first point, but other points may also be available
    pt = hoverData["points"][0]
    bbox = pt["bbox"]
    num = pt["pointNumber"]

    # don't show hover data for current location marker
    if [pt['lat'], pt['lon']] == g.latlng:
        return False, no_update, no_update

    t_row = t_clean.iloc[num]
    img_src = t_row['img']
    name = t_row['Name']

    member = t_row['member']
    member_colors = {
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

    children = [
        html.Div([
            html.Img(src=img_src, style={"width": "100%"}),
            *([html.P(member, style={"color": member_colors.get(member, "black")})] if member else []),
            html.H3(html.B(name), style={"color": "darkblue", "overflow-wrap": "break-word"}),
            html.P(address_r),
            html.P(hours_r),
            html.P(holidays_r)
        ], style={'width': '300px', 'white-space': 'normal'})
    ]

    return True, bbox, children


if __name__ == "__main__":
    app.run(debug=True)
