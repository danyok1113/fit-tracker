from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import math
import random
import requests
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'index'

# ============ DEEPSEEK R1 ============
DEEPSEEK_API_KEY = "sk-Vubl97rhcYRkP1pfTd2gPSR5KG2zEMbB6m4aCWD4Pqs9BhoEMPIP9I4gMTy1"
DEEPSEEK_URL = "https://api.gen-api.ru/api/v1/networks/deepseek-r1"


def ask_ai(user_message, context=""):
    try:
        headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {DEEPSEEK_API_KEY}'}
        system_prompt = """Ты — персональный AI-тренер в приложении Fit. 
Ты видишь ВСЕ тренировки пользователя: бег, вело, плавание, силовые.
Анализируй данные и давай советы по улучшению результатов, восстановлению и питанию.
Отвечай на русском, дружелюбно, 2-4 предложения, используй эмодзи.
НЕ ИСПОЛЬЗУЙ HTML-теги, markdown или форматирование. Отвечай ТОЛЬКО чистым текстом."""

        payload = {
            "model": "deepseek-r1",
            "messages": [{"role": "user", "content": f"{system_prompt}\n\n{context}\n\nВопрос: {user_message}"}],
            "max_tokens": 400, "temperature": 0.7, "is_sync": True
        }
        response = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            result = response.json()
            if 'response' in result and isinstance(result['response'], list):
                item = result['response'][0]
                if 'choices' in item:
                    return item['choices'][0]['message']['content']
        return None
    except Exception as e:
        print(f"AI error: {e}")
        return None


def get_fallback_response():
    return random.choice([
        "🏃 Готов к тренировке? Начни с разминки!",
        "💪 Отличный день для прогресса!",
        "🧘 Восстановление важно!"
    ])


# ============ РАСЧЁТ КАЛОРИЙ ============
def calculate_calories(user, activity):
    if not user.weight: user.weight = 70
    if not user.height: user.height = 175
    if not user.age: user.age = 25
    bmr = 10 * user.weight + 6.25 * user.height - 5 * user.age + 5
    met_values = {'running': 8.0, 'cycling': 6.0, 'swimming': 7.0, 'strength': 5.0, 'walking': 3.5}
    met = met_values.get(activity.sport_type, 6.0)
    hours = activity.duration / 3600
    return int((bmr / 24) * met * hours)


# ============ МОДЕЛИ ============
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(120), default='')
    password_hash = db.Column(db.String(200), nullable=False)
    weight = db.Column(db.Float, default=70.0)
    height = db.Column(db.Integer, default=175)
    age = db.Column(db.Integer, default=25)
    goal = db.Column(db.String(20), default='maintain')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    activities = db.relationship('Activity', backref='user', lazy=True)
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True)

    def set_password(self, password): self.password_hash = generate_password_hash(password)

    def check_password(self, password): return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username, 'name': self.name or self.username,
            'weight': self.weight, 'height': self.height, 'age': self.age, 'goal': self.goal,
            'total_distance': sum(a.distance for a in self.activities if a.sport_type in ['running', 'cycling']),
            'total_time': sum(a.duration for a in self.activities),
            'total_activities': len(self.activities),
            'total_calories': sum(a.calories or 0 for a in self.activities)
        }


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self): return {'id': self.id, 'message': self.message, 'is_user': self.is_user,
                               'created_at': self.created_at.isoformat()}


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), default='Тренировка')
    sport_type = db.Column(db.String(50), default='running')
    distance = db.Column(db.Float, default=0.0)
    duration = db.Column(db.Integer, default=0)
    calories = db.Column(db.Integer, default=0)
    sets = db.Column(db.Integer, default=0)
    exercises = db.Column(db.Text, default='')
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    avg_pace = db.Column(db.Float, default=0.0)
    avg_speed = db.Column(db.Float, default=0.0)
    notes = db.Column(db.Text, default='')

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'sport_type': self.sport_type,
            'distance': round(self.distance, 2), 'duration': self.duration,
            'calories': self.calories, 'sets': self.sets, 'exercises': self.exercises,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'avg_pace': round(self.avg_pace, 2) if self.avg_pace else 0,
            'avg_speed': round(self.avg_speed, 2) if self.avg_speed else 0,
            'notes': self.notes
        }


class TrackPoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    elevation = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, nullable=False)
    speed = db.Column(db.Float)


class PersonalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    distance_km = db.Column(db.Float, nullable=False)
    best_time = db.Column(db.Integer, nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'))
    achieved_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))


def check_and_save_personal_records(user_id, activity):
    if activity.sport_type not in ['running', 'cycling']: return []
    distance_km = activity.distance / 1000
    record_distances = [1, 5, 10, 21.1, 42.2]
    new_records = []
    for rec_dist in record_distances:
        if distance_km >= rec_dist * 0.98:
            time_for_distance = int(activity.duration * (rec_dist / distance_km))
            existing = PersonalRecord.query.filter_by(user_id=user_id, distance_km=rec_dist).first()
            if not existing or time_for_distance < existing.best_time:
                if existing:
                    existing.best_time = time_for_distance
                    existing.activity_id = activity.id
                    existing.achieved_at = datetime.utcnow()
                else:
                    db.session.add(PersonalRecord(user_id=user_id, distance_km=rec_dist, best_time=time_for_distance,
                                                  activity_id=activity.id))
                new_records.append({'distance': rec_dist, 'time': time_for_distance})
    if new_records: db.session.commit()
    return new_records


# ============ API ============
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        if User.query.filter_by(username=data['username']).first(): return jsonify(
            {'error': 'Пользователь уже существует'}), 400
        user = User(username=data['username'], name=data.get('name', ''))
        user.set_password(data['password'])
        db.session.add(user);
        db.session.commit()
        login_user(user)
        return jsonify(user.to_dict())
    except Exception as e:
        db.session.rollback(); return jsonify({'error': str(e)}), 500


@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        user = User.query.filter_by(username=data['username']).first()
        if user and user.check_password(data['password']): login_user(user); return jsonify(user.to_dict())
        return jsonify({'error': 'Неверный логин или пароль'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/logout', methods=['POST'])
@login_required
def logout(): logout_user(); return jsonify({'message': 'Logged out'})


@app.route('/api/user', methods=['GET'])
@login_required
def get_user(): return jsonify(current_user.to_dict())


@app.route('/api/user/params', methods=['POST'])
@login_required
def update_user_params():
    try:
        data = request.json
        current_user.weight = data.get('weight', current_user.weight)
        current_user.height = data.get('height', current_user.height)
        current_user.age = data.get('age', current_user.age)
        current_user.goal = data.get('goal', current_user.goal)
        db.session.commit()
        return jsonify({'message': 'OK'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/stats', methods=['GET'])
@login_required
def get_user_stats():
    activities = Activity.query.filter_by(user_id=current_user.id).all()
    stats = {'running': {'distance': 0, 'calories': 0}, 'cycling': {'distance': 0, 'calories': 0},
             'swimming': {'distance': 0, 'calories': 0}, 'strength': {'count': 0, 'calories': 0}}
    for a in activities:
        if a.sport_type in stats:
            if a.sport_type == 'strength':
                stats['strength']['count'] += 1
            else:
                stats[a.sport_type]['distance'] += a.distance
            stats[a.sport_type]['calories'] += a.calories or 0
    return jsonify(stats)


@app.route('/api/user/stats/weekly', methods=['GET'])
@login_required
def get_weekly_stats():
    week_ago = datetime.utcnow() - timedelta(days=7)
    activities = Activity.query.filter(Activity.user_id == current_user.id, Activity.start_time >= week_ago).all()
    return jsonify({
        'total_distance': sum(a.distance for a in activities if a.sport_type in ['running', 'cycling']),
        'total_calories': sum(a.calories or 0 for a in activities),
        'total_activities': len(activities),
        'total_time': sum(a.duration for a in activities),
        'streak': 0
    })


@app.route('/api/activities', methods=['GET'])
@login_required
def get_activities():
    activities = Activity.query.filter_by(user_id=current_user.id).order_by(Activity.start_time.desc()).all()
    return jsonify([a.to_dict() for a in activities])


@app.route('/api/activities/<int:activity_id>', methods=['GET'])
@login_required
def get_activity(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    if activity.user_id != current_user.id: return jsonify({'error': 'Access denied'}), 403
    return jsonify(activity.to_dict())


@app.route('/api/activities', methods=['POST'])
@login_required
def create_activity():
    try:
        data = request.json
        start_str = data['start_time'].replace('Z', '+00:00')
        activity = Activity(user_id=current_user.id, name=data.get('name', 'Тренировка'),
                            sport_type=data.get('sport_type', 'running'), distance=data.get('distance', 0),
                            duration=data.get('duration', 0), calories=0, sets=data.get('sets', 0),
                            exercises=json.dumps(data.get('exercises', [])) if data.get('exercises') else '',
                            start_time=datetime.fromisoformat(start_str), notes=data.get('notes', ''))
        db.session.add(activity);
        db.session.flush()
        for point in data.get('track_points', []):
            db.session.add(TrackPoint(activity_id=activity.id, latitude=point['latitude'], longitude=point['longitude'],
                                      timestamp=datetime.fromisoformat(point['timestamp'].replace('Z', '+00:00'))))
        activity.calories = calculate_calories(current_user, activity)
        db.session.commit()
        if activity.duration > 0 and activity.distance > 0 and activity.sport_type in ['running', 'cycling']:
            activity.avg_pace = activity.duration / (activity.distance / 1000)
            activity.avg_speed = (activity.distance / 1000) / (activity.duration / 3600)
            db.session.commit()
        new_records = check_and_save_personal_records(current_user.id, activity)
        result = activity.to_dict();
        result['new_records'] = new_records
        return jsonify(result)
    except Exception as e:
        print(f"Ошибка: {e}"); db.session.rollback(); return jsonify({'error': str(e)}), 500


@app.route('/api/activities/<int:activity_id>', methods=['DELETE'])
@login_required
def delete_activity(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    if activity.user_id != current_user.id: return jsonify({'error': 'Access denied'}), 403
    db.session.delete(activity);
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@app.route('/activities/add')
@login_required
def add_activity_page(): return render_template('add_activity.html')


@app.route('/api/activities/manual', methods=['POST'])
@login_required
def create_manual_activity():
    try:
        data = request.json
        activity = Activity(user_id=current_user.id, name=data.get('name', 'Тренировка'),
                            sport_type=data.get('sport_type', 'running'), distance=data.get('distance', 0),
                            duration=data.get('duration', 0), start_time=datetime.fromisoformat(data['start_time']),
                            notes=data.get('notes', ''), sets=data.get('sets', 0),
                            exercises=json.dumps(data.get('exercises', [])) if data.get('exercises') else '')
        if data.get('weight'): current_user.weight = data['weight']
        db.session.add(activity);
        db.session.flush()
        activity.calories = calculate_calories(current_user, activity)
        db.session.commit()
        if activity.duration > 0 and activity.distance > 0 and activity.sport_type in ['running', 'cycling']:
            activity.avg_pace = activity.duration / (activity.distance / 1000)
            activity.avg_speed = (activity.distance / 1000) / (activity.duration / 3600)
            db.session.commit()
        new_records = check_and_save_personal_records(current_user.id, activity)
        result = activity.to_dict();
        result['new_records'] = new_records
        return jsonify(result)
    except Exception as e:
        db.session.rollback(); return jsonify({'error': str(e)}), 500


@app.route('/api/activities/<int:activity_id>/points')
@login_required
def get_activity_points(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    if activity.user_id != current_user.id: return jsonify({'error': 'Access denied'}), 403
    points = TrackPoint.query.filter_by(activity_id=activity_id).order_by(TrackPoint.timestamp).all()
    return jsonify(
        [{'latitude': p.latitude, 'longitude': p.longitude, 'timestamp': p.timestamp.isoformat()} for p in points])


@app.route('/api/personal_records', methods=['GET'])
@login_required
def get_personal_records():
    records = PersonalRecord.query.filter_by(user_id=current_user.id).order_by(PersonalRecord.distance_km).all()
    return jsonify(
        [{'distance': r.distance_km, 'time': r.best_time, 'achieved_at': r.achieved_at.isoformat()} for r in records])


# ============ AI ЧАТ ============
@app.route('/ai')
@login_required
def ai_coach_page(): return render_template('ai_chat.html')


@app.route('/api/ai/chat', methods=['POST'])
@login_required
def ai_chat():
    try:
        data = request.json;
        user_message = data.get('message', '')
        db.session.add(ChatMessage(user_id=current_user.id, message=user_message, is_user=True));
        db.session.commit()

        # Полная статистика по всем типам
        activities = Activity.query.filter_by(user_id=current_user.id).all()
        running = [a for a in activities if a.sport_type == 'running']
        cycling = [a for a in activities if a.sport_type == 'cycling']
        swimming = [a for a in activities if a.sport_type == 'swimming']
        strength = [a for a in activities if a.sport_type == 'strength']

        context = "СТАТИСТИКА ТРЕНИРОВОК:\n"
        if running:
            dist = sum(a.distance for a in running) / 1000
            context += f"🏃 Бег: {len(running)} тренировок, {dist:.2f} км\n"
        if cycling:
            dist = sum(a.distance for a in cycling) / 1000
            context += f"🚴 Вело: {len(cycling)} тренировок, {dist:.2f} км\n"
        if swimming:
            dist = sum(a.distance for a in swimming)
            context += f"🏊 Плавание: {len(swimming)} тренировок, {dist:.0f} м\n"
        if strength:
            sets = sum(a.sets or 0 for a in strength)
            context += f"🏋️ Силовые: {len(strength)} тренировок, {sets} подходов\n"

        context += "\nПОСЛЕДНИЕ 5 ТРЕНИРОВОК:\n"
        for a in activities[:5]:
            date = a.start_time.strftime('%d.%m.%Y')
            if a.sport_type == 'strength':
                details = f"{a.sets or 0} подх."
            elif a.sport_type == 'swimming':
                details = f"{a.distance:.0f} м"
            else:
                details = f"{a.distance / 1000:.2f} км"
            context += f"- {date}: {a.sport_type} — {details}, {a.duration // 60} мин\n"

        reply = ask_ai(user_message, context) or get_fallback_response()
        db.session.add(ChatMessage(user_id=current_user.id, message=reply, is_user=False));
        db.session.commit()
        return jsonify({'reply': reply})
    except Exception as e:
        return jsonify({'reply': get_fallback_response()})


@app.route('/api/ai/history', methods=['GET'])
@login_required
def get_chat_history():
    messages = ChatMessage.query.filter_by(user_id=current_user.id).order_by(ChatMessage.created_at.asc()).limit(
        50).all()
    return jsonify([m.to_dict() for m in messages])


@app.route('/api/ai/clear', methods=['POST'])
@login_required
def clear_chat_history():
    ChatMessage.query.filter_by(user_id=current_user.id).delete();
    db.session.commit()
    return jsonify({'message': 'Cleared'})


# ============ СТРАНИЦЫ ============
@app.route('/')
def index():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/dashboard')
@login_required
def dashboard(): return render_template('dashboard.html')


@app.route('/tracker')
@login_required
def tracker(): return render_template('tracker_mobile.html')


@app.route('/activities')
@login_required
def activities_list(): return render_template('activities.html')


@app.route('/activity/<int:activity_id>')
@login_required
def activity_detail(activity_id): return render_template('activity_detail.html', activity_id=activity_id)


@app.route('/profile')
@login_required
def profile(): return render_template('profile.html')


@app.route('/charts')
@login_required
def charts_page(): return render_template('charts.html')


@app.route('/records')
@login_required
def records_page(): return render_template('records.html')


@app.route('/analysis')
@login_required
def analysis_page(): return render_template('analysis.html')


@app.route('/goals')
@login_required
def goals_page(): return render_template('goals.html')


@app.route('/manifest.json')
def manifest(): return send_from_directory('static', 'manifest.json')


@app.route('/sw.js')
def service_worker(): return send_from_directory('static', 'sw.js')


# ============ ЗАПУСК ============
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✅ База готова!")
    app.run(debug=False, host='0.0.0.0', port=5000)