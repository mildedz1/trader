from app.signing import build_pre_md5_string, md5_upper_hex, SpotSigner, PerpSigner


def test_build_pre_md5_string_and_md5_upper():
    params = {
        "b": "2",
        "a": "1",
        "signature_method": "HmacSHA256",
        "timestamp": "1700000000000",
        "echostr": "ABC",
    }
    s = build_pre_md5_string(params)
    assert s.startswith("a=1&b=2&")
    md5u = md5_upper_hex(s)
    assert md5u == md5u.upper()


def test_hmac_sign_spot_and_perp_same_algo():
    params = {
        "symbol": "btc_usdt",
        "price": "30000",
        "amount": "0.01",
        "timestamp": "1700000000000",
        "signature_method": "HmacSHA256",
        "echostr": "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
    }
    secret = "test_secret"
    spot = SpotSigner(secret_key=secret)
    perp = PerpSigner(secret_key=secret)

    headers_s, signed_s = spot.build_headers_and_signature(params.copy())
    headers_p, signed_p = perp.build_headers_and_signature(params.copy())

    assert "sign" in signed_s and "sign" in signed_p
    assert signed_s["sign"] == signed_p["sign"]
    assert headers_s["Content-Type"] == "application/x-www-form-urlencoded"
    assert headers_p["Content-Type"] == "application/json"
