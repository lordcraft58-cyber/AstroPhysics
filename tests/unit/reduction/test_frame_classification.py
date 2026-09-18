from __future__ import annotations

from astrophysics_suite.reduction.frame_classification import classify_frame_type, classify_session_headers


def test_classify_frame_type_recognizes_common_imagetyp_variants():
    assert classify_frame_type({"IMAGETYP": "Bias Frame"}) == "bias"
    assert classify_frame_type({"IMAGETYP": "BIAS"}) == "bias"
    assert classify_frame_type({"IMAGETYP": "dark"}) == "dark"
    assert classify_frame_type({"IMAGETYP": "Dark Frame"}) == "dark"
    assert classify_frame_type({"IMAGETYP": "Flat Field"}) == "flat"
    assert classify_frame_type({"IMAGETYP": "DomeFlat"}) == "flat"
    assert classify_frame_type({"IMAGETYP": "Light Frame"}) == "light"
    assert classify_frame_type({"IMAGETYP": "OBJECT"}) == "light"


def test_classify_frame_type_falls_back_to_obstype_or_frametyp():
    assert classify_frame_type({"OBSTYPE": "flat"}) == "flat"
    assert classify_frame_type({"FRAMETYP": "dark"}) == "dark"


def test_classify_frame_type_never_guesses_when_no_evidence():
    assert classify_frame_type({}) == "unknown"
    assert classify_frame_type({"OBJECT": "M31"}) == "unknown"  # OBJECT no es IMAGETYP
    assert classify_frame_type({"IMAGETYP": "something weird"}) == "unknown"


def test_classify_session_headers_extracts_exptime_and_filter():
    headers = {
        "bias_0.fits": {"IMAGETYP": "Bias Frame"},
        "flat_0.fits": {"IMAGETYP": "Flat Field", "FILTER": "OIII", "EXPTIME": 5.0},
        "light_0.fits": {"IMAGETYP": "Light Frame", "FILTER": "HA", "EXPTIME": 300.0},
        "mystery.fits": {},
    }

    classified = classify_session_headers(headers)
    by_path = {c.path: c for c in classified}

    assert by_path["bias_0.fits"].frame_type == "bias"
    assert by_path["bias_0.fits"].exposure_s is None
    assert by_path["flat_0.fits"].frame_type == "flat"
    assert by_path["flat_0.fits"].exposure_s == 5.0
    assert by_path["flat_0.fits"].filter_name == "OIII"
    assert by_path["light_0.fits"].frame_type == "light"
    assert by_path["light_0.fits"].exposure_s == 300.0
    assert by_path["mystery.fits"].frame_type == "unknown"
