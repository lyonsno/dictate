from spoke import backdrop_stream, metal_warp


def test_optical_shell_warp_tuning_constants_match_backdrop_renderer():
    shared_constant_names = (
        "_WARP_BLEED_ZONE_FRAC",
        "_WARP_CENTER_FLOOR",
        "_WARP_FIELD_EXPONENT",
        "_WARP_REMAP_BASE_EXP_SCALE",
        "_WARP_REMAP_BASE_EXP_FLOOR",
        "_WARP_REMAP_RIM_EXP",
        "_WARP_CURVEBOOST_CAP",
        "_WARP_CURVEBOOST_MAG_SCALE",
        "_WARP_CURVEBOOST_RING_DIVISOR",
        "_WARP_CURVEBOOST_RING_CAP",
        "_WARP_SPINE_PROXIMITY_BOOST",
        "_WARP_X_SQUEEZE",
        "_WARP_Y_SQUEEZE",
        "_WARP_EXTERIOR_MAG_STRENGTH",
        "_WARP_EXTERIOR_MAG_DECAY",
    )

    for name in shared_constant_names:
        assert getattr(metal_warp, name) == getattr(backdrop_stream, name), name


def test_warp_alias_mip_bias_stays_zero_for_near_identity_warp():
    assert metal_warp._warp_alias_mip_bias(1.0, 1.0) == 0.0
    assert metal_warp._warp_alias_mip_bias(1.08, 0.96) == 0.0


def test_warp_alias_mip_bias_rises_for_violent_warp():
    assert metal_warp._warp_alias_mip_bias(2.6, 1.7) > 0.0
    assert metal_warp._warp_alias_mip_bias(0.38, 0.52) > 0.0
