"""The signer against AWS's published example (Signature Version 4, "GET Bucket (List Objects)")."""

from datetime import UTC, datetime

from ashley.files import sigv4

KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AT = datetime(2013, 5, 24, tzinfo=UTC)


def test_the_published_example_signature_is_reproduced() -> None:
    headers = sigv4.sign("GET", "examplebucket.s3.amazonaws.com", "/", {"max-keys": "2", "prefix": "J"}, b"", KEY,
                         SECRET, AT)
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;x-amz-content-sha256;x-amz-date, "
        "Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7")
    assert headers["x-amz-date"] == "20130524T000000Z"


def test_the_body_and_the_secret_change_the_signature() -> None:
    base = sigv4.sign("PUT", "h", "/b/k", {}, b"one", KEY, SECRET, AT)["authorization"]
    assert sigv4.sign("PUT", "h", "/b/k", {}, b"two", KEY, SECRET, AT)["authorization"] != base
    assert sigv4.sign("PUT", "h", "/b/k", {}, b"one", KEY, SECRET + "x", AT)["authorization"] != base
