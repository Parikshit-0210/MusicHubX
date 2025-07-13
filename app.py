import os
from flask import Response, Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from werkzeug.utils import secure_filename
import mutagen
from mutagen.mp3 import MP3
import random
import json
from datetime import datetime  # Added for timestamp handling
import mimetypes

app = Flask(__name__)
app.secret_key = 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6'  # Replace with a secure key

# Serve the songs directory statically
app.config['SONGS_DIR'] = os.path.join(os.getcwd(), 'songs')

# Database connection configuration
DB_CONFIG = {
    'dbname': 'music_streaming',
    'user': 'postgres',  # Replace with your PostgreSQL username
    'password': 'admin',  # Replace with your PostgreSQL password
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

# Helper function to check if user is premium
def is_premium_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT current_subscription_plan_id FROM users WHERE user_id = %s",
            (user_id,)
        )
        user = cur.fetchone()
        return user['current_subscription_plan_id'] is not None and user['current_subscription_plan_id'] != 1  # Assuming plan_id 1 is Free
    finally:
        cur.close()
        conn.close()

# Helper function to check if the user is admin
def is_admin():
    return 'user_id' in session and session.get('email') == 'admin@gmail.com'

# Serve song files with permission checks and range request support
@app.route('/songs/<filename>')
def serve_song(filename):
    if 'user_id' not in session:
        flash("Please log in to play songs.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_is_premium = is_premium_user(user_id)

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Fetch the track by name (filename without .mp3)
        track_name = filename.rsplit('.', 1)[0]  # Remove the .mp3 extension
        cur.execute("SELECT track_id, is_premium FROM tracks WHERE name = %s", (track_name,))
        track = cur.fetchone()
        if not track:
            flash("Track not found.", "error")
            return redirect(url_for('player'))

        # Check if the track is premium and the user is not premium
        if track['is_premium'] and not user_is_premium:
            flash("This track is premium. Please upgrade your subscription to play it.", "error")
            return redirect(url_for('subscription'))

        file_path = os.path.join(app.config['SONGS_DIR'], filename)
        if not os.path.exists(file_path):
            flash("Song file not found.", "error")
            return redirect(url_for('player'))

        # Get the file size
        file_size = os.path.getsize(file_path)

        # Handle range requests for seeking
        range_header = request.headers.get('Range', None)
        if not range_header:
            # No range request, stream the entire file
            def generate_full():
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(1024 * 1024)  # Read 1MB at a time
                        if not chunk:
                            break
                        yield chunk

            mime_type, _ = mimetypes.guess_type(file_path)
            return Response(generate_full(), mimetype=mime_type, headers={
                "Content-Length": str(file_size),
                "Content-Disposition": "inline",
                "Accept-Ranges": "bytes"
            }, status=200)

        # Parse the range header (e.g., "bytes=0-1023")
        range_str = range_header.replace("bytes=", "")
        start, end = range_str.split("-")
        start = int(start)
        end = int(end) if end else file_size - 1

        # Ensure the range is valid
        if start >= file_size:
            return Response(status=416)  # Range Not Satisfiable

        if end >= file_size:
            end = file_size - 1

        content_length = end - start + 1

        # Stream the requested range
        def generate_range():
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk_size = min(1024 * 1024, remaining)  # Read 1MB at a time or remaining bytes
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)

        mime_type, _ = mimetypes.guess_type(file_path)
        return Response(generate_range(), mimetype=mime_type, headers={
            "Content-Length": str(content_length),
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Disposition": "inline",
            "Accept-Ranges": "bytes"
        }, status=206)  # Partial Content

    except Exception as e:
        flash(f"Error serving song: {str(e)}", "error")
        return redirect(url_for('player'))
    finally:
        cur.close()
        conn.close()

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch some featured tracks (e.g., most played tracks across all users)
    cur.execute(
        """
        SELECT 
            t.track_id,
            t.name AS track_name,
            a.name AS artist_name,
            g.name AS genre_name,
            t.is_premium,
            COUNT(l.track_id) AS play_count
        FROM tracks t
        LEFT JOIN creates c ON t.track_id = c.track_id
        LEFT JOIN artists a ON c.artist_id = a.artist_id
        LEFT JOIN genre g ON t.genre_id = g.genre_id
        LEFT JOIN plays_queue l ON t.track_id = l.track_id
        GROUP BY t.track_id, t.name, a.name, g.name
        ORDER BY play_count DESC
        LIMIT 5
        """
    )
    featured_tracks = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('home.html', featured_tracks=featured_tracks, is_premium_user=is_premium_user(user_id))

# User Authentication
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('player'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        dob = request.form['dob']
        plan_id = request.form.get('plan_id', None)

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "CALL signup_user(%s, %s, %s, %s, %s, NULL, NULL)",
                (name, email, password, dob, plan_id)
            )
            conn.commit()
            result = cur.fetchone()
            if result['p_status'] == 'Signup successful':
                flash('Signup successful! Please log in.')
                return redirect(url_for('login'))
            else:
                flash(result['p_status'])
        except Exception as e:
            flash(f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "CALL login_user(%s, %s, NULL, NULL, NULL)",
                (email, password)
            )
            conn.commit()
            result = cur.fetchone()
            if result['p_status'] == 'Login successful':
                session['user_id'] = result['p_user_id']
                session['name'] = result['p_name']
                session['email'] = email  # Store email in session for admin check
                # Check if the user is admin and redirect accordingly
                if email == 'admin@gmail.com':
                    flash('Admin Login Successful!',"success")
                    return redirect(url_for('admin_dashboard'))
                else:
                    flash('Login Successful!', "success")
                    return redirect(url_for('index'))
            else:
                flash(result['p_status'])
        except Exception as e:
            flash(f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('name', None)
    session.pop('email', None)  # Clear email from session
    session.pop('current_track', None)
    session.pop('context_type', None)
    session.pop('context_id', None)
    session.pop('shuffle', None)
    session.pop('repeat', None)
    session.pop('playlist_tracks', None)
    flash('Logout Successful!', "success")
    return redirect(url_for('login'))

# Profile Management
@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()

    # Fetch user details
    cur.execute("SELECT name, email, date_of_birth FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    # Fetch top 10 tracks based on listens
    cur.execute(
        """
        SELECT 
            t.track_id,
            t.name AS track_name,
            a.name AS artist_name,
            g.name AS genre_name,
            t.is_premium,
            COUNT(l.track_id) AS play_count
        FROM plays_queue l
        JOIN tracks t ON l.track_id = t.track_id
        LEFT JOIN creates c ON t.track_id = c.track_id
        LEFT JOIN artists a ON c.artist_id = a.artist_id
        LEFT JOIN genre g ON t.genre_id = g.genre_id
        WHERE l.user_id = %s
        GROUP BY t.track_id, t.name, a.name, g.name, t.is_premium
        ORDER BY play_count DESC, t.name
        LIMIT 10
        """,
        (user_id,)
    )
    top_tracks = cur.fetchall()

    # Fetch favorite artist
    cur.execute(
        """
        SELECT a.name
        FROM plays_queue l
        JOIN creates c ON l.track_id = c.track_id
        JOIN artists a ON c.artist_id = a.artist_id
        WHERE l.user_id = %s
        GROUP BY a.name
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (user_id,)
    )
    favorite_artist = cur.fetchone()

    cur.close()
    conn.close()

    return render_template(
        'profile.html',
        user=user,
        top_tracks=top_tracks,
        favorite_artist=favorite_artist,
        is_premium_user=is_premium_user(user_id)
    )

# Search Functionality
# Search Functionality
@app.route('/search')
def search():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    return render_template('search.html', query='', results=[], is_premium_user=is_premium_user(session['user_id']))

@app.route('/search_ajax', methods=['POST'])
def search_ajax():
    if 'user_id' not in session:
        print("Session error: 'user_id' not in session")
        return jsonify({'error': 'Not logged in'}), 401

    query = request.form.get('query', '').strip()
    results = []

    if query:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT 
                    t.track_id, 
                    t.name AS track_name, 
                    a.name AS artist_name, 
                    a.artist_id,  -- Added to fetch artist_id for follow/unfollow
                    g.name AS genre_name, 
                    t.is_premium,
                    CASE 
                        WHEN t.name ILIKE %s THEN 1
                        WHEN a.name ILIKE %s THEN 2
                        WHEN al.name ILIKE %s THEN 3
                        ELSE 4
                    END AS sort_priority
                FROM tracks t
                LEFT JOIN creates c ON t.track_id = c.track_id
                LEFT JOIN artists a ON c.artist_id = a.artist_id
                LEFT JOIN genre g ON t.genre_id = g.genre_id
                LEFT JOIN albums al ON t.album_id = al.album_id
                WHERE t.name ILIKE %s
                   OR (a.name ILIKE %s AND NOT t.name ILIKE %s)
                   OR (al.name ILIKE %s AND NOT t.name ILIKE %s)
                ORDER BY sort_priority, t.name
                """,
                (f"{query}%", f"{query}%", f"{query}%", f"{query}%", f"{query}%", f"{query}%", f"{query}%", f"{query}%")
            )
            results = cur.fetchall()

            # Add like and follow status to search results
            user_id = session['user_id']
            for result in results:
                # Check if the user has liked this track
                cur.execute(
                    "SELECT * FROM likes WHERE user_id = %s AND track_id = %s",
                    (user_id, result['track_id'])
                )
                result['is_liked'] = bool(cur.fetchone())

                # Check if the user is following the artist
                if result['artist_id']:
                    cur.execute(
                        "SELECT * FROM follows WHERE user_id = %s AND artist_id = %s",
                        (user_id, result['artist_id'])
                    )
                    result['is_following_artist'] = bool(cur.fetchone())
                else:
                    result['is_following_artist'] = False

        except Exception as e:
            print(f"Database error: {str(e)}")
            return jsonify({'error': f"Database error: {str(e)}"}), 500
        finally:
            cur.close()
            conn.close()
    else:
        print("No query provided")
        return jsonify({'results': [], 'is_premium_user': is_premium_user(session['user_id'])})

    results_list = [
        {
            'track_id': result['track_id'],
            'track_name': result['track_name'],
            'artist_name': result['artist_name'],
            'artist_id': result['artist_id'],
            'genre_name': result['genre_name'],
            'is_premium': result['is_premium'],
            'is_liked': result['is_liked'],
            'is_following_artist': result['is_following_artist']
        } for result in results
    ]

    return jsonify({
        'results': results_list,
        'is_premium_user': is_premium_user(session['user_id'])
    })

# Track Liking
@app.route('/like/<int:track_id>', methods=['POST'])
def like_track(track_id):
    if 'user_id' not in session:
        flash('Please log in to like tracks.')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Check if the track exists
        cur.execute("SELECT track_id FROM tracks WHERE track_id = %s", (track_id,))
        if not cur.fetchone():
            flash("Track not found.", "error")
            return redirect(request.referrer or url_for('search'))

        # Check if the user has already liked the track
        cur.execute(
            "SELECT * FROM likes WHERE user_id = %s AND track_id = %s",
            (user_id, track_id)
        )
        if cur.fetchone():
            flash("You have already liked this track.", "error")
            return redirect(request.referrer or url_for('search'))

        # Add the like with the current timestamp
        cur.execute(
            "INSERT INTO likes (user_id, track_id, like_date_time) VALUES (%s, %s, %s)",
            (user_id, track_id, datetime.now())
        )
        conn.commit()
        flash('Track liked successfully!', "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error liking track: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(request.referrer or url_for('search'))

@app.route('/unlike/<int:track_id>', methods=['POST'])
def unlike_track(track_id):
    if 'user_id' not in session:
        flash('Please log in to unlike tracks.')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Check if the user has liked the track
        cur.execute(
            "SELECT * FROM likes WHERE user_id = %s AND track_id = %s",
            (user_id, track_id)
        )
        if not cur.fetchone():
            flash("You haven't liked this track.", "error")
            return redirect(request.referrer or url_for('search'))

        # Remove the like
        cur.execute(
            "DELETE FROM likes WHERE user_id = %s AND track_id = %s",
            (user_id, track_id)
        )
        conn.commit()
        flash('Track unliked successfully!', "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error unliking track: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(request.referrer or url_for('search'))

# Artist Following
@app.route('/follow/<int:artist_id>', methods=['POST'])
def follow_artist(artist_id):
    if 'user_id' not in session:
        flash('Please log in to follow artists.')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Check if the artist exists
        cur.execute("SELECT artist_id FROM artists WHERE artist_id = %s", (artist_id,))
        if not cur.fetchone():
            flash("Artist not found.", "error")
            return redirect(request.referrer or url_for('search'))

        # Check if the user is already following the artist
        cur.execute(
            "SELECT * FROM follows WHERE user_id = %s AND artist_id = %s",
            (user_id, artist_id)
        )
        if cur.fetchone():
            flash("You are already following this artist.", "error")
            return redirect(request.referrer or url_for('search'))

        # Add the follow with the current timestamp
        cur.execute(
            "INSERT INTO follows (user_id, artist_id, follow_date_time) VALUES (%s, %s, %s)",
            (user_id, artist_id, datetime.now())
        )
        conn.commit()
        flash('Artist followed successfully!', "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error following artist: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(request.referrer or url_for('search'))

@app.route('/unfollow/<int:artist_id>', methods=['POST'])
def unfollow_artist(artist_id):
    if 'user_id' not in session:
        flash('Please log in to unfollow artists.')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Check if the user is following the artist
        cur.execute(
            "SELECT * FROM follows WHERE user_id = %s AND artist_id = %s",
            (user_id, artist_id)
        )
        if not cur.fetchone():
            flash("You are not following this artist.", "error")
            return redirect(request.referrer or url_for('search'))

        # Remove the follow
        cur.execute(
            "DELETE FROM follows WHERE user_id = %s AND artist_id = %s",
            (user_id, artist_id)
        )
        conn.commit()
        flash('Artist unfollowed successfully!', "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error unfollowing artist: {str(e)}", "error")
    finally:
        cur.close()
        conn.close()
    return redirect(request.referrer or url_for('search'))

# Playlist Management
@app.route('/playlists', methods=['GET', 'POST'])
def playlists():
    if 'user_id' not in session:
        print("User not logged in, redirecting to login")
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if request.method == 'POST':
            name = request.form['name']
            print(f"Creating new playlist: {name}")
            cur.execute(
                "INSERT INTO playlists (name, user_id) VALUES (%s, %s) RETURNING playlist_id",
                (name, session['user_id'])
            )
            conn.commit()
            flash('Playlist created successfully!', "success")
            return redirect(url_for('playlists'))

        # Fetch user-created playlists
        print(f"Fetching playlists for user_id: {session['user_id']}")
        cur.execute("SELECT * FROM playlists WHERE user_id = %s", (session['user_id'],))
        user_playlists = cur.fetchall()
        print(f"Found {len(user_playlists)} playlists: {user_playlists}")

        # Add a special "Liked Songs" playlist
        liked_songs_playlist = {
            'playlist_id': -1,  # Special ID for Liked Songs
            'name': 'Liked Songs',
            'user_id': session['user_id']
        }
        playlists = [liked_songs_playlist] + user_playlists  # Prepend Liked Songs to the list
        print(f"Total playlists (including Liked Songs): {len(playlists)}")

    except Exception as e:
        print(f"Error fetching playlists: {str(e)}")
        flash(f"Error fetching playlists: {str(e)}", "error")
        playlists = []
    finally:
        cur.close()
        conn.close()

    return render_template('playlists.html', playlists=playlists)

@app.route('/playlists/<playlist_id>', methods=['GET', 'POST'])
def playlist_details(playlist_id):
    try:
        playlist_id = int(playlist_id)  # Convert to integer manually
    except ValueError:
        flash("Invalid playlist ID.", "error")
        return redirect(url_for('playlists'))

    print(f"Accessing playlist_details for playlist_id: {playlist_id}, user_id: {session.get('user_id', 'Not set')}")
    if 'user_id' not in session:
        print("User not logged in, redirecting to login")
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Handle the special "Liked Songs" playlist
        if playlist_id == -1:  # Liked Songs playlist
            print("Handling Liked Songs playlist")
            playlist = {
                'playlist_id': -1,
                'name': 'Liked Songs',
                'user_id': session['user_id']
            }

            # Fetch liked tracks for the user
            print(f"Fetching liked tracks for user_id: {session['user_id']}")
            cur.execute(
                """
                SELECT t.*, a.name AS artist_name, a.artist_id, g.name AS genre_name
                FROM tracks t
                JOIN likes l ON t.track_id = l.track_id
                LEFT JOIN creates c ON t.track_id = c.track_id
                LEFT JOIN artists a ON c.artist_id = a.artist_id
                LEFT JOIN genre g ON t.genre_id = g.genre_id
                WHERE l.user_id = %s
                ORDER BY l.like_date_time DESC
                """,
                (session['user_id'],)
            )
            tracks = cur.fetchall()
            print(f"Found {len(tracks)} liked tracks: {tracks}")
            for track in tracks:
                track['duration'] = track['duration']

        else:
            # Fetch playlist details for regular playlists
            print(f"Fetching regular playlist with playlist_id: {playlist_id}")
            cur.execute("SELECT * FROM playlists WHERE playlist_id = %s AND user_id = %s", (playlist_id, session['user_id']))
            playlist = cur.fetchone()
            if not playlist:
                print("Playlist not found or user does not have access")
                flash('Playlist not found or you do not have access.', "error")
                return redirect(url_for('playlists'))

            if request.method == 'POST':
                track_id = request.form['track_id']
                order = request.form.get('order')
                print(f"Adding track_id: {track_id} to playlist_id: {playlist_id}")
                cur.execute(
                    "INSERT INTO included_in (playlist_id, track_id, \"order\") VALUES (%s, %s, %s)",
                    (playlist_id, track_id, order)
                )
                conn.commit()
                flash('Track added to playlist!', "success")

            # Fetch tracks with artist and genre information
            print(f"Fetching tracks for playlist_id: {playlist_id}")
            cur.execute(
                """
                SELECT t.*, a.name AS artist_name, a.artist_id, g.name AS genre_name
                FROM tracks t
                JOIN included_in i ON t.track_id = i.track_id
                LEFT JOIN creates c ON t.track_id = c.track_id
                LEFT JOIN artists a ON c.artist_id = a.artist_id
                LEFT JOIN genre g ON t.genre_id = g.genre_id
                WHERE i.playlist_id = %s
                ORDER BY i.order, t.name
                """,
                (playlist_id,)
            )
            tracks = cur.fetchall()
            print(f"Found {len(tracks)} tracks in playlist: {tracks}")
            for track in tracks:
                track['duration'] = track['duration']

        # Add like and follow status to each track
        user_id = session['user_id']
        for track in tracks:
            # Check if the user has liked this track
            cur.execute(
                "SELECT * FROM likes WHERE user_id = %s AND track_id = %s",
                (user_id, track['track_id'])
            )
            track['is_liked'] = bool(cur.fetchone())

            # Check if the user is following the artist
            if track['artist_id']:
                cur.execute(
                    "SELECT * FROM follows WHERE user_id = %s AND artist_id = %s",
                    (user_id, track['artist_id'])
                )
                track['is_following_artist'] = bool(cur.fetchone())
            else:
                track['is_following_artist'] = False

    except Exception as e:
        print(f"Error in playlist_details: {str(e)}")
        flash(f"Error loading playlist: {str(e)}", "error")
        tracks = []
        playlist = None
    finally:
        cur.close()
        conn.close()

    if not playlist:
        print("Playlist is None, redirecting to playlists")
        flash("Unable to load playlist.", "error")
        return redirect(url_for('playlists'))

    print("Rendering playlists.html with playlist and tracks")
    return render_template('playlists.html', playlists=[], playlist=playlist, tracks=tracks, is_premium_user=is_premium_user(session['user_id']))

@app.route('/playlists/<int:playlist_id>/remove/<int:track_id>', methods=['POST'])
def remove_track_from_playlist(playlist_id, track_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM included_in WHERE playlist_id = %s AND track_id = %s",
            (playlist_id, track_id)
        )
        conn.commit()
        flash('Track removed from playlist!')
    except Exception as e:
        flash(f"Error: {str(e)}")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('playlist_details', playlist_id=playlist_id))

# Music Playback with Shuffle/Repeat
@app.route('/player', methods=['GET', 'POST'])
def player():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_track = session.get('current_track', None)
    context_type = session.get('context_type', 'search')
    context_id = session.get('context_id', None)
    shuffle = session.get('shuffle', False)
    repeat = session.get('repeat', False)
    playlist_tracks = session.get('playlist_tracks', [])

    user_is_premium = is_premium_user(session['user_id'])

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            track_id = request.form.get('track_id')
            new_context_type = request.form.get('context_type', context_type)
            new_context_id = request.form.get('context_id', context_id)

            if action == 'play':
                cur.execute(
                    "SELECT is_premium FROM tracks WHERE track_id = %s",
                    (track_id,)
                )
                track = cur.fetchone()
                if track['is_premium'] and not user_is_premium:
                    flash("This track is premium. Please upgrade your subscription to play it.", "error")
                    # Redirect back to the Playlists page if context_type is 'playlist'
                    if new_context_type == 'playlist' and new_context_id:
                        return redirect(url_for('playlist_details', playlist_id=new_context_id))
                    # Fallback redirect if not coming from a playlist
                    return redirect(url_for('playlists'))
                else:
                    try:
                        cur.execute(
                            "INSERT INTO plays_queue (user_id, track_id) VALUES (%s, %s)",
                            (session['user_id'], track_id)
                        )
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        flash(f"Error logging play event: {str(e)}", "error")
                        return redirect(url_for('player'))
                    session['current_track'] = track_id
                    session['context_type'] = new_context_type
                    session['context_id'] = new_context_id

                    if new_context_type == 'playlist' and new_context_id:
                        cur.execute(
                            "SELECT t.track_id FROM tracks t JOIN included_in i ON t.track_id = i.track_id WHERE i.playlist_id = %s ORDER BY i.order",
                            (new_context_id,)
                        )
                        tracks = cur.fetchall()
                        session['playlist_tracks'] = [track['track_id'] for track in tracks]

            elif action == 'next':
                if repeat and current_track:
                    try:
                        cur.execute(
                            "INSERT INTO plays_queue (user_id, track_id) VALUES (%s, %s)",
                            (session['user_id'], current_track)
                        )
                        conn.commit()
                    except Exception as e:
                        conn.rollback()
                        flash(f"Error logging play event: {str(e)}", "error")
                        return redirect(url_for('player'))
                else:
                    cur.execute(
                        "SELECT * FROM get_next_track(%s, %s, %s, %s)",
                        (session['user_id'], current_track, context_type, context_id)
                    )
                    next_track = cur.fetchone()
                    if next_track:
                        cur.execute(
                            "SELECT is_premium FROM tracks WHERE track_id = %s",
                            (next_track['next_track_id'],)
                        )
                        track = cur.fetchone()
                        if track['is_premium'] and not user_is_premium:
                            flash("The next track is premium. Please upgrade your subscription to play it.", "error")
                            # Redirect back to the Playlists page if context_type is 'playlist'
                            if context_type == 'playlist' and context_id:
                                return redirect(url_for('playlist_details', playlist_id=context_id))
                            return redirect(url_for('playlists'))
                        else:
                            try:
                                cur.execute(
                                    "INSERT INTO plays_queue (user_id, track_id) VALUES (%s, %s)",
                                    (session['user_id'], next_track['next_track_id'])
                                )
                                conn.commit()
                            except Exception as e:
                                conn.rollback()
                                flash(f"Error logging play event: {str(e)}", "error")
                                return redirect(url_for('player'))
                            session['current_track'] = next_track['next_track_id']
                    elif shuffle and context_type == 'playlist' and playlist_tracks:
                        next_track_id = random.choice(playlist_tracks)
                        cur.execute(
                            "SELECT is_premium FROM tracks WHERE track_id = %s",
                            (next_track_id,)
                        )
                        track = cur.fetchone()
                        if track['is_premium'] and not user_is_premium:
                            flash("The shuffled track is premium. Please upgrade your subscription to play it.", "error")
                            # Redirect back to the Playlists page if context_type is 'playlist'
                            if context_type == 'playlist' and context_id:
                                return redirect(url_for('playlist_details', playlist_id=context_id))
                            return redirect(url_for('playlists'))
                        else:
                            try:
                                cur.execute(
                                    "INSERT INTO plays_queue (user_id, track_id) VALUES (%s, %s)",
                                    (session['user_id'], next_track_id)
                                )
                                conn.commit()
                            except Exception as e:
                                conn.rollback()
                                flash(f"Error logging play event: {str(e)}", "error")
                                return redirect(url_for('player'))
                            session['current_track'] = next_track_id

            elif action == 'shuffle':
                session['shuffle'] = not shuffle
            elif action == 'repeat':
                session['repeat'] = not repeat

        if current_track:
            cur.execute(
                "SELECT t.*, a.name AS artist_name, g.name AS genre_name "
                "FROM tracks t "
                "LEFT JOIN creates c ON t.track_id = c.track_id "
                "LEFT JOIN artists a ON c.artist_id = a.artist_id "
                "LEFT JOIN genre g ON t.genre_id = g.genre_id "
                "WHERE t.track_id = %s", (current_track,))
            current_track_details = cur.fetchone()
        else:
            current_track_details = None

        try:
            cur.execute(
                """
                SELECT t.*, a.name AS artist_name, a.artist_id, g.name AS genre_name
                FROM tracks t
                LEFT JOIN creates c ON t.track_id = c.track_id
                LEFT JOIN artists a ON c.artist_id = a.artist_id
                LEFT JOIN genre g ON t.genre_id = g.genre_id
                ORDER BY t.name
                """
            )
            all_tracks = cur.fetchall()
            for track in all_tracks:
                # Check if the user has liked this track
                cur.execute(
                    "SELECT * FROM likes WHERE user_id = %s AND track_id = %s",
                    (session['user_id'], track['track_id'])
                )
                track['is_liked'] = bool(cur.fetchone())
                # Check if the user is following the artist
                if track['artist_id']:
                    cur.execute(
                        "SELECT * FROM follows WHERE user_id = %s AND artist_id = %s",
                        (session['user_id'], track['artist_id'])
                    )
                    track['is_following_artist'] = bool(cur.fetchone())
                else:
                    track['is_following_artist'] = False

        except Exception as e:
            flash(f"Error fetching all tracks: {str(e)}", "error")
            all_tracks = []

    except Exception as e:
        flash(f"Error in player route: {str(e)}", "error")
        all_tracks = []
    finally:
        cur.close()
        conn.close()

    return render_template(
        'player.html',
        current_track=current_track_details,
        all_tracks=all_tracks,
        shuffle=session.get('shuffle', False),
        repeat=session.get('repeat', False),
        is_premium_user=user_is_premium
    )

# Existing routes for adding genre, artist, album (to be removed or modified)
@app.route('/add_genre', methods=['POST'])
def add_genre():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_genre = request.form.get('new_genre')
    if not new_genre:
        flash('Genre name is required.')
        return redirect(url_for('upload_track'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO genre (name) VALUES (%s)", (new_genre,))
        conn.commit()
        flash('Genre added successfully!')
    except Exception as e:
        conn.rollback()
        flash(f"Error adding genre: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('upload_track'))

@app.route('/add_artist', methods=['POST'])
def add_artist():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_artist = request.form.get('new_artist')
    genre_id = request.form.get('artist_genre_id')
    if not all([new_artist, genre_id]):
        flash('Artist name and genre are required.')
        return redirect(url_for('upload_track'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO artists (name, genre_id) VALUES (%s, %s)", (new_artist, genre_id))
        conn.commit()
        flash('Artist added successfully!')
    except Exception as e:
        conn.rollback()
        flash(f"Error adding artist: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('upload_track'))

@app.route('/add_album', methods=['POST'])
def add_album():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_album = request.form.get('new_album')
    artist_id = request.form.get('album_artist_id')
    release_date = request.form.get('release_date')
    if not all([new_album, artist_id, release_date]):
        flash('Album name, artist, and release date are required.')
        return redirect(url_for('upload_track'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO albums (name, release_date, artist_id) VALUES (%s, %s, %s)",
            (new_album, release_date, artist_id)
        )
        conn.commit()
        flash('Album added successfully!')
    except Exception as e:
        conn.rollback()
        flash(f"Error adding album: {str(e)}")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('upload_track'))

# Define allowed file extensions
ALLOWED_EXTENSIONS = {'mp3'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload', methods=['GET', 'POST'])
def upload_track():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if request.method == 'POST':
            if 'file' not in request.files:
                flash('No file part')
                return redirect(request.url)
            file = request.files['file']
            if file.filename == '':
                flash('No selected file')
                return redirect(request.url)
            if not allowed_file(file.filename):
                flash('Invalid file type. Only .mp3 files are allowed.')
                return redirect(request.url)

            track_name = request.form.get('track_name')
            artist_id = request.form.get('artist_id')
            genre_id = request.form.get('genre_id')
            album_id = request.form.get('album_id')
            is_premium = request.form.get('is_premium') == 'on'

            if not all([track_name, artist_id, genre_id, album_id]):
                flash('All fields are required.')
                return redirect(request.url)

            cur.execute("SELECT track_id FROM tracks WHERE name = %s", (track_name,))
            if cur.fetchone():
                flash('A track with this name already exists. Please choose a different name.')
                return redirect(request.url)

            filename = secure_filename(track_name + '.mp3')
            file_path = os.path.join(app.config['SONGS_DIR'], filename)
            file.save(file_path)

            audio = MP3(file_path)
            duration_seconds = int(audio.info.length)  # Duration in seconds

            # Convert duration to INTERVAL format (e.g., '239 seconds')
            duration_interval = f"{duration_seconds} seconds"

            cur.execute(
                """
                INSERT INTO tracks (name, duration, is_premium, genre_id, album_id, play_count)
                VALUES (%s, %s::interval, %s, %s, %s, %s)
                RETURNING track_id
                """,
                (track_name, duration_interval, is_premium, genre_id, album_id, 0)
            )
            track_id = cur.fetchone()['track_id']

            cur.execute(
                "INSERT INTO creates (artist_id, track_id) VALUES (%s, %s)",
                (artist_id, track_id)
            )

            conn.commit()
            flash('Track uploaded successfully!')
            return redirect(url_for('player'))

        cur.execute("SELECT * FROM genre")
        genres = cur.fetchall()
        cur.execute("SELECT * FROM artists")
        artists = cur.fetchall()
        cur.execute("SELECT * FROM albums")
        albums = cur.fetchall()

    except Exception as e:
        conn.rollback()
        flash(f"Error uploading track: {str(e)}")
        genres = artists = albums = []
    finally:
        cur.close()
        conn.close()

    return render_template('upload.html', genres=genres, artists=artists, albums=albums)

# Route to download a song
@app.route('/download/<int:track_id>')
def download_track(track_id):
    if 'user_id' not in session:
        flash("Please log in to download songs.", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']
    if not is_premium_user(user_id):
        flash("Upgrade to a premium plan to download songs!", "error")
        return redirect(url_for('subscription'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Fetch the track details
        cur.execute("SELECT name FROM tracks WHERE track_id = %s", (track_id,))
        track = cur.fetchone()
        if not track:
            flash("Track not found.", "error")
            return redirect(url_for('home'))

        # Construct the file path
        filename = secure_filename(track['name'] + '.mp3')
        file_path = os.path.join(app.config['SONGS_DIR'], filename)
        if not os.path.exists(file_path):
            flash("Song file not found.", "error")
            return redirect(url_for('home'))

        # Send the file for download
        return send_from_directory(app.config['SONGS_DIR'], filename, as_attachment=True)

    except Exception as e:
        flash(f"Error downloading track: {str(e)}", "error")
        return redirect(url_for('home'))
    finally:
        cur.close()
        conn.close()

# Premium Subscription with History
@app.route('/subscription', methods=['GET', 'POST'])
def subscription():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Initialize variables with default values
    plans = []
    subscription_history = []

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'subscribe':
                plan_id = request.form.get('plan_id')
                payment_method = request.form.get('payment_method')
                cur.execute("SELECT price FROM subscription_plan WHERE plan_id = %s", (plan_id,))
                plan = cur.fetchone()
                if plan:
                    amount = plan['price']
                    # Process payment
                    cur.execute("CALL process_payment(%s, %s, %s, %s)",
                                (session['user_id'], plan_id, payment_method, amount))
                    # Subscribe to the plan and fetch p_status
                    cur.execute("CALL subscribe_to_plan(%s, %s, %s)",
                                (session['user_id'], plan_id, ''))
                    status = cur.fetchone()
                    if status and 'p_status' in status:
                        flash(status['p_status'])
                    else:
                        flash("Error retrieving subscription status")
                    conn.commit()
                else:
                    flash("Invalid plan selected")
            elif action == 'cancel':
                # Cancel the subscription and fetch p_status
                cur.execute("CALL cancel_subscription(%s, %s)",
                            (session['user_id'], ''))
                status = cur.fetchone()
                if status and 'p_status' in status:
                    flash(status['p_status'])
                else:
                    flash("Error retrieving cancellation status")
                conn.commit()

        # Fetch subscription plans
        cur.execute("SELECT * FROM subscription_plan")
        plans = cur.fetchall()

        # Fetch subscription history using the stored procedure
        cur.execute("CALL get_subscription_history(%s, %s, %s, %s, %s, %s)",
                    (session['user_id'], None, None, None, None, 'subscription_history_cursor'))
        cur.execute("FETCH ALL FROM subscription_history_cursor")
        subscription_history = cur.fetchall()

    except Exception as e:
        flash(f"Error in subscription route: {str(e)}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

    return render_template('subscription.html', plans=plans, subscription_history=subscription_history)

@app.route('/cancel_subscription', methods=['POST'])
def cancel_subscription():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "CALL cancel_subscription(%s, NULL)",
            (session['user_id'],)
        )
        conn.commit()
        result = cur.fetchone()
        flash(result['p_status'])
    except Exception as e:
        flash(f"Error: {str(e)}")
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('subscription'))

# --- Admin Routes ---

# Admin dashboard route
@app.route('/admin/dashboard')
def admin_dashboard():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Fetch genres, artists, and albums for the Add Track form
        cur.execute("SELECT * FROM genre")
        genres = cur.fetchall()
        cur.execute("SELECT * FROM artists")
        artists = cur.fetchall()
        cur.execute("SELECT * FROM albums")
        albums = cur.fetchall()
    except Exception as e:
        flash(f"Error fetching data: {str(e)}", 'error')
        genres = artists = albums = []
    finally:
        cur.close()
        conn.close()

    return render_template('admin.html', genres=genres, artists=artists, albums=albums)

# Admin logout route
@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))
# Route to add a new artist
@app.route('/admin/add_artist', methods=['POST'])
def admin_add_artist():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']
    email = request.form['email']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL add_artist(%s, %s, %s, %s)',
                (name, email, None, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))

# Route to remove an artist
@app.route('/admin/remove_artist', methods=['POST'])
def admin_remove_artist():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL remove_artist(%s, %s)',
                (name, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))
# Route to add a new album
@app.route('/admin/add_album', methods=['POST'])
def admin_add_album():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']
    release_date = request.form['release_date']
    artist_name = request.form['artist_name']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL add_album(%s, %s, %s, %s, %s)',
                (name, release_date, artist_name, None, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))
# Route to remove an album
@app.route('/admin/remove_album', methods=['POST'])
def admin_remove_album():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL remove_album(%s, %s)',
                (name, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))
# Route to add a new genre
@app.route('/admin/add_genre', methods=['POST'])
def admin_add_genre():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL add_genre(%s, %s, %s)',
                (name, None, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))

# Route to remove a genre
@app.route('/admin/remove_genre', methods=['POST'])
def admin_remove_genre():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL remove_genre(%s, %s)',
                (name, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))


# Route to add a new track
@app.route('/admin/add_track', methods=['POST'])
def admin_add_track():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    # Validate form data
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('admin_dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('admin_dashboard'))

    if not allowed_file(file.filename):
        flash('Invalid file type. Only .mp3 files are allowed.', 'error')
        return redirect(url_for('admin_dashboard'))

    track_name = request.form.get('track_name')
    artist_id = request.form.get('artist_id')
    genre_id = request.form.get('genre_id')
    album_id = request.form.get('album_id') if request.form.get('album_id') else None
    is_premium = 'is_premium' in request.form  # Checkbox returns 'on' if checked

    if not all([track_name, artist_id, genre_id]):
        flash('Track name, artist, and genre are required.', 'error')
        return redirect(url_for('admin_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Check if a track with this name already exists
        cur.execute("SELECT track_id FROM tracks WHERE name = %s", (track_name,))
        if cur.fetchone():
            flash('A track with this name already exists. Please choose a different name.', 'error')
            return redirect(url_for('admin_dashboard'))

        # Save the file
        filename = secure_filename(track_name + '.mp3')
        file_path = os.path.join(app.config['SONGS_DIR'], filename)
        file.save(file_path)

        # Calculate duration using mutagen
        audio = MP3(file_path)
        duration_seconds = int(audio.info.length)  # Duration in seconds
        duration_interval = f"{duration_seconds} seconds"

        # Add the track to the database
        cur.execute(
            'CALL add_track(%s, %s, %s, %s, %s, %s, %s, %s)',
            (track_name, duration_interval, genre_id, is_premium, album_id, artist_id, None, None)
        )
        result = cur.fetchone()
        conn.commit()

        flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    except Exception as e:
        conn.rollback()
        flash(f"Error adding track: {str(e)}", 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin_dashboard'))
# Route to remove a track
@app.route('/admin/remove_track', methods=['POST'])
def admin_remove_track():
    if not is_admin():
        flash('You must be an admin to access this page', 'error')
        return redirect(url_for('login'))

    name = request.form['name']

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('CALL remove_track(%s, %s)',
                (name, None))
    result = cur.fetchone()
    cur.close()
    conn.commit()
    conn.close()

    flash(result['p_status'], 'success' if 'successfully' in result['p_status'] else 'error')
    return redirect(url_for('admin_dashboard'))
# --- End of Admin Routes ---

if __name__ == '__main__':
    app.run(debug=True)
