# fr-dgtl-transcript-video-poc

POC d'un transcript d'une video via l'API Speech to Text

I. Create .env:

```bash
# Will store audio files created from video, used by Speech to Text API
BUCKET_NAME="speech-to-text-ahtest"
# Specify how to split audio content
# i.e for a 1 hour video, SEGMENT_DIVIDER=6 will create 6 audio file with 10m length, and concurrently transcript them
# Very usefull for long video, keep 1 for very short content
SEGMENT_DIVIDER=1
```

II. Install dependencies

```bash
python3 -m venv venv
pip install -r requirements.txt

# + ffmpeg dependency
# brew install ffmpeg
# apt-get install ffmpeg
```

III. Create 'videos/' directory and add a video to transcript in.

IV. Run script

```bash
python3 main.py <my_video_in_videos_folder>
```
