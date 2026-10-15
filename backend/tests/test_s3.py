import unittest
from unittest.mock import patch, MagicMock

from app.s3 import sanitize_filename, generate_presigned_put_url


class TestS3Helper(unittest.TestCase):
    def test_sanitize_filename_valid(self):
        self.assertEqual(sanitize_filename("users.csv"), "users.csv")
        self.assertEqual(sanitize_filename("data_2026-10.CSV"), "data_2026-10.CSV")

    def test_sanitize_filename_strips_path(self):
        self.assertEqual(sanitize_filename("../../../secret/data.csv"), "data.csv")
        self.assertEqual(sanitize_filename("C:\\Windows\\Temp\\data.csv"), "data.csv")

    def test_sanitize_filename_replaces_invalid_chars(self):
        self.assertEqual(sanitize_filename("user file (1) & test.csv"), "user_file__1____test.csv")
        self.assertEqual(sanitize_filename("test@example#data.csv"), "test_example_data.csv")

    def test_sanitize_filename_rejects_non_csv(self):
        with self.assertRaises(ValueError):
            sanitize_filename("users.xlsx")
        with self.assertRaises(ValueError):
            sanitize_filename("users.txt")
        with self.assertRaises(ValueError):
            sanitize_filename("script.py")
        with self.assertRaises(ValueError):
            sanitize_filename("")

    @patch("boto3.client")
    def test_generate_presigned_put_url(self, mock_boto3_client):
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://s3.ap-south-1.amazonaws.com/test-bucket/test-key?sig=abc"
        mock_boto3_client.return_value = mock_s3

        url = generate_presigned_put_url(
            bucket_name="test-bucket",
            s3_key="uploads/batch-123/users.csv",
            region_name="ap-south-1",
            expires_in=900,
        )

        mock_boto3_client.assert_called_once()
        _, kwargs = mock_boto3_client.call_args
        self.assertEqual(kwargs.get("region_name"), "ap-south-1")
        self.assertEqual(kwargs.get("endpoint_url"), "https://s3.ap-south-1.amazonaws.com")

        mock_s3.generate_presigned_url.assert_called_once_with(
            ClientMethod="put_object",
            Params={
                "Bucket": "test-bucket",
                "Key": "uploads/batch-123/users.csv",
            },
            ExpiresIn=900,
        )
        self.assertIn("https://", url)


if __name__ == "__main__":
    unittest.main()
