import os
import shutil

# Root of the test dataset
TEST_ROOT = "test_media"

# Sample shows + episodes
SHOWS = {
    "Severance": [
        ("Severance - S01E01 - Good News About Hell 1080p.mkv",),
        ("Severance - S01E02 - Half Loop 1080p.mkv",),
    ],
    "Breaking Bad": [
        ("Breaking Bad - S01E01 - Pilot 720p.mp4",),
        ("Breaking Bad - S01E02 - Cat's in the Bag 720p.mp4",),
    ],
}

# Sample movies
MOVIES = [
    "Inception 1080p.mkv",
    "The Matrix 1999 4k.mp4"
]

def create_structure():
    # Clean old
    if os.path.exists(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(TEST_ROOT)

    # TV Shows
    tv_root = os.path.join(TEST_ROOT, "tvshows")
    os.makedirs(tv_root)

    for show, episodes in SHOWS.items():
        show_dir = os.path.join(tv_root, show)
        os.makedirs(show_dir)
        for ep in episodes:
            fpath = os.path.join(show_dir, ep[0])
            with open(fpath, "wb") as f:
                f.write(b"FAKEVIDEO")  # just placeholder content

    # Movies
    movie_root = os.path.join(TEST_ROOT, "movies")
    os.makedirs(movie_root)
    for m in MOVIES:
        fpath = os.path.join(movie_root, m)
        with open(fpath, "wb") as f:
            f.write(b"FAKEMOVIE")

    print(f"✅ Seed data created under: {TEST_ROOT}")

if __name__ == "__main__":
    create_structure()