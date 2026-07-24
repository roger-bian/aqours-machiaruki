"""Structural validation for a freshly downloaded KML export.

The KML from the last successful pipeline run (kept in Supabase Storage,
see `BASELINE_KML_KEY` in app/main.py) is treated as the accepted
structure. A newly downloaded KML is checked against it before any DB
write is attempted; if it deviates too much, `PipelineValidationError` is
raised and the caller must discard the new download rather than upsert
anything.
"""

REQUIRED_COLUMNS = {'Name', 'Description', 'geometry_object'}

# how far the new placemark count may drop from the baseline before it's
# treated as a structural break (e.g. a botched export) rather than a
# handful of stores closing
MIN_COUNT_RATIO = 0.5

# labels/images are allowed to be missing for a few entries in normal data
# (see app/description.py), but if too many are missing at once that's a
# sign the Description HTML format itself changed
MAX_EMPTY_ADDRESS_RATIO = 0.1
MAX_EMPTY_IMG_RATIO = 0.1


class PipelineValidationError(Exception):
    pass


def validate_structure(placemarks, baseline_count, fields_by_row):
    """Raise PipelineValidationError if `placemarks` deviates too much from
    the accepted structure. `fields_by_row` is the list of parsed
    description fields (as returned by parse_description) plus `img_url`,
    one per placemark row, in row order.
    """
    missing_columns = REQUIRED_COLUMNS - set(placemarks.columns)
    if missing_columns:
        raise PipelineValidationError(f'missing expected columns: {sorted(missing_columns)}')

    count = len(placemarks)
    if count == 0:
        raise PipelineValidationError('no placemarks found in downloaded KML')
    if baseline_count and count < baseline_count * MIN_COUNT_RATIO:
        raise PipelineValidationError(
            f'placemark count dropped too far: {count} vs baseline {baseline_count}'
        )

    for _, row in placemarks.iterrows():
        if not str(row['Name']).strip():
            raise PipelineValidationError('placemark with empty Name')
        try:
            row.geometry_object.y, row.geometry_object.x
        except AttributeError:
            raise PipelineValidationError('placemark with non-point geometry')
        if row.geometry_object.geom_type != 'Point':
            raise PipelineValidationError(
                f'placemark with unexpected geometry type: {row.geometry_object.geom_type}'
            )

    empty_address = sum(1 for f in fields_by_row if not f['address'])
    if empty_address / count > MAX_EMPTY_ADDRESS_RATIO:
        raise PipelineValidationError(
            f'too many placemarks missing address: {empty_address}/{count}'
        )

    empty_img = sum(1 for f in fields_by_row if not f['img_url'])
    if empty_img / count > MAX_EMPTY_IMG_RATIO:
        raise PipelineValidationError(
            f'too many placemarks missing image: {empty_img}/{count}'
        )
