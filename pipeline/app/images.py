import hashlib
import mimetypes
import os

import requests

from app.storage import upload_image


def cache_images(urls, img_dir):
    # Google's hosted-image CDN (mymaps.usercontent.google.com) blocks/rate-limits
    # these requests when made from a browser tab, so images are downloaded
    # once here (server-side) and uploaded to a Supabase Storage bucket. The
    # local dir is purely a download cache (skip re-hitting Google's CDN on
    # every pipeline run) - the frontend reads img_url (Supabase Storage),
    # not this directory.
    os.makedirs(img_dir, exist_ok=True)
    cached = {name.split('.')[0]: name for name in os.listdir(img_dir)}

    urls_out = []
    for url in urls:
        if not url:
            urls_out.append('')
            continue

        digest = hashlib.sha1(url.encode()).hexdigest()
        filename = cached.get(digest)
        if filename is None:
            response = requests.get(url)
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
            ext = mimetypes.guess_extension(content_type) or '.jpg'
            filename = digest + ext
            with open(os.path.join(img_dir, filename), 'wb') as f:
                f.write(response.content)
            cached[digest] = filename

        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        with open(os.path.join(img_dir, filename), 'rb') as f:
            content = f.read()
        public_url = upload_image(filename, content, content_type)
        urls_out.append(public_url)
    return urls_out
