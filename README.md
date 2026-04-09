# Finger Vein Attendance Prototype

This Flask project is a starter system for:

- enrolling multiple users with finger-vein samples
- removing enrolled users through an admin dashboard
- marking attendance from a public screen with one button
- capturing images from a Raspberry Pi camera using `picamera2`, `rpicam-still`, or an OpenCV camera fallback

## Hardware Notes

For clear vein images, use:

- Raspberry Pi 4 Model B
- Pi Camera Module 3 NoIR
- near-infrared LEDs, usually 850nm or 940nm
- a closed finger slot to block ambient light

The camera should face the finger while the NIR light shines through or around the finger in a fixed position. Normal room light is usually not enough for reliable vein contrast.

## Software Setup

1. Install system packages on Raspberry Pi OS:

```bash
sudo apt update
sudo apt install python3-venv python3-picamera2 libcamera-apps
```

2. Create a virtual environment and install Python packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Start the web app:

```bash
python3 run.py
```

4. Open:

```text
http://localhost:5000
```

## Admin Login

- Username: `admin`
- Password: `admin123`

Override them with environment variables if needed:

```bash
export VEIN_ADMIN_USER=admin
export VEIN_ADMIN_PASSWORD=strong-password
```

## How It Works

- `/` shows the attendance screen
- `/admin/login` opens the admin login
- `/admin` lets the admin enroll or remove users
- enrollment captures multiple samples for each user
- attendance capture compares the current finger-vein template with stored templates

## Important Prototype Note

This is a baseline recognition pipeline, not a production biometric model. You will likely need to tune:

- LED placement
- exposure and focus
- finger guide dimensions
- match threshold with your real hardware

On Raspberry Pi OS Bookworm, the app can work even if `picamera2` is missing, as long as `rpicam-still` is installed and the web app process has access to the camera device.

The default match threshold is controlled with:

```bash
export VEIN_MATCH_THRESHOLD=0.58
```
