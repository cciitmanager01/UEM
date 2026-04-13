import socket

# Replace with JUST the domain from your Supabase URL
# Example: "wvpjnrzmpdswhjnkskbb.supabase.co"
hostname = "wvpjnrzmpdswhjnkskbb.supabase.co"

try:
    addr = socket.gethostbyname(hostname)
    print(f"Success! The IP for Supabase is: {addr}")
except Exception as e:
    print(f"Failed to find Supabase: {e}")