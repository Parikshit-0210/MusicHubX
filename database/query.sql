-- Create database
CREATE DATABASE music_streaming;
\c music_streaming;

-- Create tables with constraints
CREATE TABLE users (
    user_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    password VARCHAR(255) NOT NULL CHECK (LENGTH(password) >= 8),
    date_of_birth DATE CHECK (date_of_birth <= CURRENT_DATE - INTERVAL '13 years'),
    current_subscription_plan_id INT
);

CREATE TABLE artists (
    artist_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE TABLE subscription_plan (
    plan_id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    price DECIMAL(10, 2) NOT NULL CHECK (price >= 0),
    description TEXT
);

CREATE TABLE tracks (
    track_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    duration VARCHAR(10) CHECK (duration ~ '^[0-9]{1,2}\.[0-5][0-9]$'), -- MM.SS format
    genre_id INT,
    is_premium BOOLEAN DEFAULT FALSE,
    play_count INTEGER DEFAULT 0 CHECK (play_count >= 0),
    album_id INT
);

CREATE TABLE albums (
    album_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    release_date DATE CHECK (release_date <= CURRENT_DATE),
    artist_id INT REFERENCES artists(artist_id)
);

CREATE TABLE playlists (
    playlist_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    user_id INT REFERENCES users(user_id)
);

CREATE TABLE genres (
    genre_id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE payment (
    payment_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    plan_id INT REFERENCES subscription_plan(plan_id),
    method VARCHAR(50) NOT NULL CHECK (method IN ('credit_card', 'debit_card', 'paypal', 'bank_transfer')),
    amount DECIMAL(10, 2) NOT NULL CHECK (amount >= 0),
    payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP CHECK (payment_date <= CURRENT_TIMESTAMP)
);

CREATE TABLE likes (
    user_id INT REFERENCES users(user_id),
    track_id INT REFERENCES tracks(track_id),
    like_date_time TIMESTAMP CHECK (like_date_time <= CURRENT_TIMESTAMP),
    PRIMARY KEY (user_id, track_id)
);

CREATE TABLE follows (
    user_id INT REFERENCES users(user_id),
    artist_id INT REFERENCES artists(artist_id),
    follow_date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP CHECK (follow_date_time <= CURRENT_TIMESTAMP),
    PRIMARY KEY (user_id, artist_id)
);

CREATE TABLE contains (
    album_id INT REFERENCES albums(album_id),
    track_id INT REFERENCES tracks(track_id),
    PRIMARY KEY (album_id, track_id)
);

CREATE TABLE creates (
    artist_id INTEGER REFERENCES artists(artist_id),
    track_id INTEGER REFERENCES tracks(track_id),
    PRIMARY KEY (artist_id, track_id)
);

CREATE TABLE plays_queue (
    play_id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(user_id),
    track_id INT REFERENCES tracks(track_id),
    play_date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP CHECK (play_date_time <= CURRENT_TIMESTAMP)
);

CREATE TABLE included_in (
    playlist_id INT REFERENCES playlists(playlist_id),
    track_id INT REFERENCES tracks(track_id),
    "order" INT CHECK ("order" >= 0),
    PRIMARY KEY (playlist_id, track_id)
);

CREATE TABLE has_similarity (
    track_id1 INT REFERENCES tracks(track_id),
    track_id2 INT REFERENCES tracks(track_id),
    similarity_score FLOAT CHECK (similarity_score >= 0 AND similarity_score <= 1),
    PRIMARY KEY (track_id1, track_id2),
    CHECK (track_id1 < track_id2) -- Prevent duplicate pairs
);

CREATE TABLE subscription_history (
    subscription_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id),
    plan_id INTEGER REFERENCES subscription_plan(plan_id),
    start_date TIMESTAMP NOT NULL CHECK (start_date <= CURRENT_TIMESTAMP),
    end_date TIMESTAMP CHECK (end_date IS NULL OR (end_date > start_date AND end_date <= CURRENT_TIMESTAMP))
);

-- Add foreign key constraints
ALTER TABLE users
ADD CONSTRAINT fk_users_subscription_plan
FOREIGN KEY (current_subscription_plan_id) REFERENCES subscription_plan(plan_id);

ALTER TABLE tracks
ADD CONSTRAINT fk_tracks_genre
FOREIGN KEY (genre_id) REFERENCES genres(genre_id),
ADD CONSTRAINT fk_tracks_album
FOREIGN KEY (album_id) REFERENCES albums(album_id);

-- Procedure to sign up a user
CREATE OR REPLACE PROCEDURE signup_user(
    p_name VARCHAR(100),
    p_email VARCHAR(100),
    p_password VARCHAR(255),
    p_date_of_birth DATE,
    p_plan_id INT DEFAULT NULL,
    OUT p_user_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM users WHERE email = p_email) THEN
        p_status := 'User with email ' || p_email || ' already exists';
        p_user_id := NULL;
        RETURN;
    END IF;

    IF p_name IS NULL OR p_email IS NULL OR p_password IS NULL OR p_date_of_birth IS NULL THEN
        p_status := 'Invalid input: All fields (name, email, password, date of birth) are required';
        p_user_id := NULL;
        RETURN;
    END IF;

    INSERT INTO users (name, email, password, date_of_birth, current_subscription_plan_id)
    VALUES (
        p_name,
        p_email,
        p_password,
        p_date_of_birth,
        p_plan_id
    )
    RETURNING user_id INTO p_user_id;

    p_status := 'Signup successful';
EXCEPTION
    WHEN foreign_key_violation THEN
        p_status := 'Invalid subscription plan ID: ' || p_plan_id;
        p_user_id := NULL;
    WHEN others THEN
        p_status := 'Signup error: ' || SQLERRM;
        p_user_id := NULL;
END;
$$ LANGUAGE plpgsql;

-- Procedure to log in a user
CREATE OR REPLACE PROCEDURE login_user(
    p_email VARCHAR(100),
    p_password VARCHAR(255),
    OUT p_user_id INT,
    OUT p_name VARCHAR(100),
    OUT p_status VARCHAR(100)
) AS $$
DECLARE
    v_stored_password VARCHAR(255);
BEGIN
    IF p_email IS NULL OR p_password IS NULL THEN
        p_status := 'Email and password are required';
        p_user_id := NULL;
        p_name := NULL;
        RETURN;
    END IF;

    SELECT user_id, name, password INTO p_user_id, p_name, v_stored_password
    FROM users
    WHERE email = p_email;

    IF NOT FOUND THEN
        p_status := 'User with email ' || p_email || ' not found';
        p_user_id := NULL;
        p_name := NULL;
        RETURN;
    END IF;

    IF v_stored_password = p_password THEN
        p_status := 'Login successful';
    ELSE
        p_status := 'Password incorrect';
        p_user_id := NULL;
        p_name := NULL;
    END IF;
EXCEPTION
    WHEN others THEN
        p_status := 'Login error: ' || SQLERRM;
        p_user_id := NULL;
        p_name := NULL;
END;
$$ LANGUAGE plpgsql;

-- Procedure to search music
CREATE OR REPLACE PROCEDURE search_music(
    p_user_id INTEGER,
    p_query VARCHAR,
    INOUT p_result_type VARCHAR,
    INOUT p_result_id INTEGER,
    INOUT p_result_name VARCHAR,
    INOUT p_results refcursor
) AS $$
BEGIN
    OPEN p_results FOR
    SELECT 'song' AS result_type, track_id AS result_id, name AS result_name
    FROM tracks
    WHERE name ILIKE '%' || p_query || '%'
        AND (is_premium = FALSE OR EXISTS (
            SELECT 1 FROM users u
            WHERE u.user_id = p_user_id
            AND u.current_subscription_plan_id IS NOT NULL
            AND u.current_subscription_plan_id != 1
        ))
    UNION
    SELECT 'album', album_id, name
    FROM albums
    WHERE name ILIKE '%' || p_query || '%'
    UNION
    SELECT 'playlist', playlist_id, name
    FROM playlists
    WHERE name ILIKE '%' || p_query || '%'
        AND user_id = p_user_id
    UNION
    SELECT 'artist', artist_id, name
    FROM artists
    WHERE name ILIKE '%' || p_query || '%';

    p_result_type := NULL;
    p_result_id := NULL;
    p_result_name := NULL;
END;
$$ LANGUAGE plpgsql;

-- Function to get the next track
CREATE OR REPLACE FUNCTION get_next_track(
    p_user_id INTEGER,
    p_current_track_id INTEGER,
    p_context_type VARCHAR,
    p_context_id INTEGER
) RETURNS TABLE (
    next_track_id INTEGER
) AS $$
BEGIN
    IF p_context_type = 'playlist' AND p_context_id IS NOT NULL THEN
        RETURN QUERY
        SELECT t.track_id
        FROM tracks t
        JOIN included_in i ON t.track_id = i.track_id
        WHERE i.playlist_id = p_context_id
        AND i.order > (
            SELECT i2.order
            FROM included_in i2
            WHERE i2.playlist_id = p_context_id
            AND i2.track_id = p_current_track_id
        )
        AND (t.is_premium = FALSE OR EXISTS (
            SELECT 1 FROM users u
            WHERE u.user_id = p_user_id
            AND u.current_subscription_plan_id IS NOT NULL
            AND u.current_subscription_plan_id != 1
        ))
        ORDER BY i.order
        LIMIT 1;
    ELSE
        RETURN QUERY
        SELECT track_id
        FROM tracks
        WHERE track_id != p_current_track_id
        AND (is_premium = FALSE OR EXISTS (
            SELECT 1 FROM users u
            WHERE u.user_id = p_user_id
            AND u.current_subscription_plan_id IS NOT NULL
            AND u.current_subscription_plan_id != 1
        ))
        ORDER BY RANDOM()
        LIMIT 1;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to get top 10 tracks for a user
CREATE OR REPLACE FUNCTION get_top_10_tracks_for_user(p_user_id INTEGER)
RETURNS TABLE (
    track_id INTEGER,
    track_name VARCHAR,
    play_count BIGINT,
    genre_name VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.track_id,
        t.name AS track_name,
        COUNT(pq.play_id) AS play_count,
        g.name AS genre_name
    FROM tracks t
    JOIN plays_queue pq ON t.track_id = pq.track_id
    JOIN genres g ON t.genre_id = g.genre_id
    WHERE pq.user_id = p_user_id
    GROUP BY t.track_id, t.name, g.name
    ORDER BY play_count DESC
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;

select get_top_10_tracks_for_user(1);
select get_track_play_count_last_3_months(12);

-- Function to get the favorite artist name
CREATE OR REPLACE FUNCTION get_favorite_artist_name(p_user_id INTEGER)
RETURNS TABLE (
    artist_name VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.name AS artist_name
    FROM artists a
    JOIN creates c ON a.artist_id = c.artist_id
    JOIN tracks t ON c.track_id = t.track_id
    JOIN plays_queue pq ON t.track_id = pq.track_id
    WHERE pq.user_id = p_user_id
    GROUP BY a.artist_id, a.name
    ORDER BY COUNT(pq.play_id) DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to calculate track play count for the last 3 months
CREATE OR REPLACE FUNCTION get_track_play_count_last_3_months(track_id_input INT)
RETURNS INT AS $$
DECLARE
    total_plays INT;
BEGIN
    SELECT COUNT(*)
    INTO total_plays
    FROM plays_queue
    WHERE track_id = track_id_input
    AND play_date_time >= CURRENT_DATE - INTERVAL '3 months';
    RETURN COALESCE(total_plays, 0);
END;
$$ LANGUAGE plpgsql;

-- Procedure to process payment
CREATE OR REPLACE PROCEDURE process_payment(
    p_user_id INTEGER,
    p_plan_id INTEGER,
    p_method VARCHAR,
    p_amount NUMERIC
) AS $$
BEGIN
    INSERT INTO payment (user_id, plan_id, method, amount, payment_date)
    VALUES (p_user_id, p_plan_id, p_method, p_amount, CURRENT_TIMESTAMP);
EXCEPTION
    WHEN OTHERS THEN
        RAISE EXCEPTION 'Error processing payment: %', SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Procedure to subscribe to a plan
CREATE OR REPLACE PROCEDURE subscribe_to_plan(
    p_user_id INTEGER,
    p_plan_id INTEGER,
    INOUT p_status VARCHAR
) AS $$
BEGIN
    UPDATE subscription_history
    SET end_date = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id
    AND end_date IS NULL;

    INSERT INTO subscription_history (user_id, plan_id, start_date)
    VALUES (p_user_id, p_plan_id, CURRENT_TIMESTAMP);

    UPDATE users
    SET current_subscription_plan_id = p_plan_id
    WHERE user_id = p_user_id;

    p_status := 'Subscription successful';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Procedure to cancel subscription
CREATE OR REPLACE PROCEDURE cancel_subscription(
    p_user_id INTEGER,
    INOUT p_status VARCHAR
) AS $$
BEGIN
    UPDATE subscription_history
    SET end_date = CURRENT_TIMESTAMP
    WHERE user_id = p_user_id
    AND end_date IS NULL;

    UPDATE users
    SET current_subscription_plan_id = 1
    WHERE user_id = p_user_id;

    p_status := 'Subscription cancelled';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Procedure to get subscription history
CREATE OR REPLACE PROCEDURE get_subscription_history(
    p_user_id INTEGER,
    INOUT p_plan_name VARCHAR,
    INOUT p_start_date TIMESTAMP,
    INOUT p_end_date TIMESTAMP,
    INOUT p_action VARCHAR,
    INOUT p_history refcursor
) AS $$
BEGIN
    OPEN p_history FOR
    SELECT
        sp.name AS plan_name,
        sh.start_date,
        sh.end_date,
        CASE
            WHEN sh.end_date IS NULL THEN 'Subscribed'
            ELSE 'Cancelled'
        END AS action
    FROM subscription_history sh
    JOIN subscription_plan sp ON sh.plan_id = sp.plan_id
    WHERE sh.user_id = p_user_id
    ORDER BY sh.start_date DESC;

    p_plan_name := NULL;
    p_start_date := NULL;
    p_end_date := NULL;
    p_action := NULL;
END;
$$ LANGUAGE plpgsql;

-- Function to update play count
CREATE OR REPLACE FUNCTION update_play_count()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE tracks
    SET play_count = play_count + 1
    WHERE track_id = NEW.track_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update play count
CREATE TRIGGER update_play_count_trigger
AFTER INSERT ON plays_queue
FOR EACH ROW
EXECUTE FUNCTION update_play_count();

-- Insert the admin user (email: admin, password: admin)
INSERT INTO users (name, email, password, date_of_birth, current_subscription_plan_id)
VALUES (
    'Admin',
    'admin',
    'admin', -- Hash the password 'admin'
    '1970-01-01', -- Arbitrary date of birth
    NULL -- No subscription plan for admin
);

-- Procedure to add a new artist
CREATE OR REPLACE PROCEDURE add_artist(
    p_name VARCHAR(100),
    p_email VARCHAR(100),
    OUT p_artist_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM artists WHERE email = p_email) THEN
        p_status := 'Artist with email ' || p_email || ' already exists';
        p_artist_id := NULL;
        RETURN;
    END IF;

    INSERT INTO artists (name, email)
    VALUES (p_name, p_email)
    RETURNING artist_id INTO p_artist_id;

    p_status := 'Artist added successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error adding artist: ' || SQLERRM;
        p_artist_id := NULL;
END;
$$ LANGUAGE plpgsql;

-- Procedure to remove an artist
CREATE OR REPLACE PROCEDURE remove_artist(
    p_artist_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM artists WHERE artist_id = p_artist_id) THEN
        p_status := 'Artist with ID ' || p_artist_id || ' does not exist';
        RETURN;
    END IF;

    DELETE FROM creates WHERE artist_id = p_artist_id;
    DELETE FROM follows WHERE artist_id = p_artist_id;
    DELETE FROM albums WHERE artist_id = p_artist_id;
    DELETE FROM artists WHERE artist_id = p_artist_id;

    p_status := 'Artist removed successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error removing artist: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Procedure to add a new album
CREATE OR REPLACE PROCEDURE add_album(
    p_name VARCHAR(100),
    p_release_date DATE,
    p_artist_id INT,
    OUT p_album_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM artists WHERE artist_id = p_artist_id) THEN
        p_status := 'Artist with ID ' || p_artist_id || ' does not exist';
        p_album_id := NULL;
        RETURN;
    END IF;

    INSERT INTO albums (name, release_date, artist_id)
    VALUES (p_name, p_release_date, p_artist_id)
    RETURNING album_id INTO p_album_id;

    p_status := 'Album added successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error adding album: ' || SQLERRM;
        p_album_id := NULL;
END;
$$ LANGUAGE plpgsql;

-- Procedure to remove an album
CREATE OR REPLACE PROCEDURE remove_album(
    p_album_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM albums WHERE album_id = p_album_id) THEN
        p_status := 'Album with ID ' || p_album_id || ' does not exist';
        RETURN;
    END IF;

    DELETE FROM contains WHERE album_id = p_album_id;
    DELETE FROM tracks WHERE album_id = p_album_id;
    DELETE FROM albums WHERE album_id = p_album_id;

    p_status := 'Album removed successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error removing album: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Procedure to add a new genre
CREATE OR REPLACE PROCEDURE add_genre(
    p_name VARCHAR(50),
    OUT p_genre_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM genres WHERE name = p_name) THEN
        p_status := 'Genre ' || p_name || ' already exists';
        p_genre_id := NULL;
        RETURN;
    END IF;

    INSERT INTO genres (name)
    VALUES (p_name)
    RETURNING genre_id INTO p_genre_id;

    p_status := 'Genre added successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error adding genre: ' || SQLERRM;
        p_genre_id := NULL;
END;
$$ LANGUAGE plpgsql;

-- Procedure to remove a genre
CREATE OR REPLACE PROCEDURE remove_genre(
    p_genre_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM genres WHERE genre_id = p_genre_id) THEN
        p_status := 'Genre with ID ' || p_genre_id || ' does not exist';
        RETURN;
    END IF;

    UPDATE tracks SET genre_id = NULL WHERE genre_id = p_genre_id;
    DELETE FROM genres WHERE genre_id = p_genre_id;

    p_status := 'Genre removed successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error removing genre: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Procedure to add a new track
CREATE OR REPLACE PROCEDURE add_track(
    p_name VARCHAR(100),
    p_duration VARCHAR(10),
    p_genre_id INT,
    p_is_premium BOOLEAN,
    p_album_id INT,
    p_artist_id INT,
    OUT p_track_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM artists WHERE artist_id = p_artist_id) THEN
        p_status := 'Artist with ID ' || p_artist_id || ' does not exist';
        p_track_id := NULL;
        RETURN;
    END IF;

    IF p_album_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM albums WHERE album_id = p_album_id) THEN
        p_status := 'Album with ID ' || p_album_id || ' does not exist';
        p_track_id := NULL;
        RETURN;
    END IF;

    IF p_genre_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM genres WHERE genre_id = p_genre_id) THEN
        p_status := 'Genre with ID ' || p_genre_id || ' does not exist';
        p_track_id := NULL;
        RETURN;
    END IF;

    INSERT INTO tracks (name, duration, genre_id, is_premium, album_id, play_count)
    VALUES (p_name, p_duration, p_genre_id, p_is_premium, p_album_id, 0)
    RETURNING track_id INTO p_track_id;

    INSERT INTO creates (artist_id, track_id)
    VALUES (p_artist_id, p_track_id);

    IF p_album_id IS NOT NULL THEN
        INSERT INTO contains (album_id, track_id)
        VALUES (p_album_id, p_track_id);
    END IF;

    p_status := 'Track added successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error adding track: ' || SQLERRM;
        p_track_id := NULL;
END;
$$ LANGUAGE plpgsql;

-- Procedure to remove a track
CREATE OR REPLACE PROCEDURE remove_track(
    p_track_id INT,
    OUT p_status VARCHAR(100)
) AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM tracks WHERE track_id = p_track_id) THEN
        p_status := 'Track with ID ' || p_track_id || ' does not exist';
        RETURN;
    END IF;

    DELETE FROM creates WHERE track_id = p_track_id;
    DELETE FROM contains WHERE track_id = p_track_id;
    DELETE FROM included_in WHERE track_id = p_track_id;
    DELETE FROM likes WHERE track_id = p_track_id;
    DELETE FROM plays_queue WHERE track_id = p_track_id;
    DELETE FROM has_similarity WHERE track_id1 = p_track_id OR track_id2 = p_track_id;
    DELETE FROM tracks WHERE track_id = p_track_id;

    p_status := 'Track removed successfully';
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'Error removing track: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE PROCEDURE add_track_to_playlist_by_name(
    p_playlist_id INTEGER,
    p_track_name VARCHAR,
    p_order INTEGER,
    INOUT p_status VARCHAR
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_track_id INTEGER;
    v_count INTEGER;
BEGIN
    -- Count the number of tracks with the given name
    SELECT COUNT(*) INTO v_count
    FROM tracks
    WHERE name = p_track_name;

    IF v_count = 0 THEN
        p_status := 'Track not found: ' || p_track_name;
        RETURN;
    ELSIF v_count > 1 THEN
        p_status := 'Multiple tracks found with name: ' || p_track_name || '. Please use a unique track name.';
        RETURN;
    END IF;

    -- Find the track ID by name
    SELECT track_id INTO v_track_id
    FROM tracks
    WHERE name = p_track_name;

    -- Check if the track is already in the playlist
    SELECT COUNT(*) INTO v_count
    FROM included_in
    WHERE playlist_id = p_playlist_id AND track_id = v_track_id;

    IF v_count > 0 THEN
        p_status := 'Track is already in the playlist: ' || p_track_name;
        RETURN;
    END IF;

    -- Insert the track into the playlist
    INSERT INTO included_in (playlist_id, track_id, "order")
    VALUES (p_playlist_id, v_track_id, p_order);

    p_status := 'Track added to playlist successfully';
EXCEPTION WHEN OTHERS THEN
    p_status := 'Error adding track to playlist: ' || SQLERRM;
END;
$$;
--Function to get the top 5 Feature tracks
CREATE OR REPLACE FUNCTION get_top_played_tracks()
RETURNS TABLE (
    track_id INTEGER,
    track_name VARCHAR(100),
    artist_name VARCHAR(100),
    genre_name VARCHAR(50),
    is_premium BOOLEAN,
    play_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
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
    LEFT JOIN genres g ON t.genre_id = g.genre_id  -- Fixed table name from 'genre' to 'genres'
    LEFT JOIN plays_queue l ON t.track_id = l.track_id
    GROUP BY t.track_id, t.name, a.name, g.name
    ORDER BY play_count DESC
    LIMIT 5;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_user_top_tracks(p_user_id INTEGER)
RETURNS TABLE (
    track_id INTEGER,
    track_name VARCHAR(100),
    artist_name VARCHAR(100),
    genre_name VARCHAR(50),
    is_premium BOOLEAN,
    play_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
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
    LEFT JOIN genre g ON t.genre_id = g.genre_id  -- Fixed table name to 'genres'
    WHERE l.user_id = p_user_id
    GROUP BY t.track_id, t.name, a.name, g.name, t.is_premium
    ORDER BY play_count DESC, t.name
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION get_user_top_artist(p_user_id INTEGER)
RETURNS VARCHAR(100) AS $$
DECLARE
    top_artist VARCHAR(100);
BEGIN
    SELECT a.name INTO top_artist
    FROM plays_queue l
    JOIN creates c ON l.track_id = c.track_id
    JOIN artists a ON c.artist_id = a.artist_id
    WHERE l.user_id = p_user_id
    GROUP BY a.name
    ORDER BY COUNT(*) DESC
    LIMIT 1;

    RETURN top_artist;
END;
$$ LANGUAGE plpgsql;
SELECT get_user_top_artist(12);
select * from users;

SELECT a.name
        FROM plays_queue l
        JOIN creates c ON l.track_id = c.track_id
        JOIN artists a ON c.artist_id = a.artist_id
        WHERE l.user_id = 12
        GROUP BY a.name
        ORDER BY COUNT(*) DESC
        LIMIT 1