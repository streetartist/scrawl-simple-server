from flask import Flask, request, jsonify
import sqlite3
import uuid
import time
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = Flask(__name__)

# SQLite数据库路径配置
DB_PATH = os.getenv('DB_PATH', 'cloud_variables.db')

def get_db_connection():
    """获取SQLite数据库连接"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as err:
        print(f"Error connecting to database: {err}")
        return None

def init_db():
    """初始化数据库表"""
    conn = get_db_connection()
    if conn is None:
        return False

    try:
        cursor = conn.cursor()

        # 创建项目表 - 移除了project_name和api_key
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL
            )
        """)

        # 创建变量表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS variables (
                project_id TEXT NOT NULL,
                var_name TEXT NOT NULL,
                var_value TEXT NOT NULL,
                last_updated REAL NOT NULL,
                PRIMARY KEY (project_id, var_name),
                FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
            )
        """)

        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_last_accessed ON projects(last_accessed)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_variables_project ON variables(project_id)")

        conn.commit()
        print("Database tables initialized")
        return True
    except sqlite3.Error as err:
        print(f"Database initialization error: {err}")
        return False
    finally:
        if conn:
            conn.close()

# 初始化数据库
init_db()

@app.route('/api/register', methods=['POST'])
def register_project():
    """注册新项目 - 只需生成project_id"""
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed'}), 500

    project_id = str(uuid.uuid4())
    created_at = time.time()

    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO projects (project_id, created_at, last_accessed) "
            "VALUES (?, ?, ?)",
            (project_id, created_at, created_at)
        conn.commit()
        return jsonify({'project_id': project_id}), 201
    except sqlite3.Error as err:
        return jsonify({'error': str(err)}), 500
    finally:
        conn.close()

@app.route('/api/<project_id>/set', methods=['POST'])
def set_variable(project_id):
    """设置变量 - 移除了API key验证"""
    data = request.get_json()
    var_name = data.get('var_name')
    var_value = data.get('var_value')

    if not var_name or var_value is None:
        return jsonify({'error': 'Missing var_name or var_value'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cursor = conn.cursor()

        # 验证项目是否存在并更新访问时间
        cursor.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,)
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Project not found'}), 404

        current_time = time.time()
        cursor.execute(
            "UPDATE projects SET last_accessed = ? WHERE project_id = ?",
            (current_time, project_id)
        )

        # 序列化复杂数据
        serialized_value = json.dumps(var_value)

        # 插入或更新变量
        cursor.execute(
            "INSERT INTO variables (project_id, var_name, var_value, last_updated) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(project_id, var_name) DO UPDATE SET "
            "var_value = excluded.var_value, last_updated = excluded.last_updated",
            (project_id, var_name, serialized_value, current_time)
        )

        conn.commit()
        return jsonify({'status': 'success'}), 200
    except sqlite3.Error as err:
        return jsonify({'error': str(err)}), 500
    except (TypeError, OverflowError) as err:
        return jsonify({'error': f'Invalid data: {str(err)}'}), 400
    finally:
        conn.close()

@app.route('/api/<project_id>/get', methods=['GET'])
def get_variable(project_id):
    """获取变量 - 移除了API key验证"""
    var_name = request.args.get('var_name')
    if not var_name:
        return jsonify({'error': 'Missing var_name'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cursor = conn.cursor()

        # 验证项目是否存在并更新访问时间
        cursor.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,)
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Project not found'}), 404

        current_time = time.time()
        cursor.execute(
            "UPDATE projects SET last_accessed = ? WHERE project_id = ?",
            (current_time, project_id)
        )

        # 获取变量值
        cursor.execute(
            "SELECT var_value, last_updated FROM variables "
            "WHERE project_id = ? AND var_name = ?",
            (project_id, var_name)
        )
        result = cursor.fetchone()

        if not result:
            return jsonify({'error': 'Variable not found'}), 404

        # 反序列化JSON数据
        try:
            value = json.loads(result['var_value'])
        except json.JSONDecodeError:
            value = result['var_value']

        return jsonify({
            'var_value': value,
            'last_updated': result['last_updated']
        }), 200
    except sqlite3.Error as err:
        return jsonify({'error': str(err)}), 500
    finally:
        conn.close()

@app.route('/api/<project_id>/all', methods=['GET'])
def get_all_variables(project_id):
    """获取所有变量 - 移除了API key验证"""
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cursor = conn.cursor()

        # 验证项目是否存在并更新访问时间
        cursor.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,)
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Project not found'}), 404

        current_time = time.time()
        cursor.execute(
            "UPDATE projects SET last_accessed = ? WHERE project_id = ?",
            (current_time, project_id)
        )

        # 获取所有变量
        cursor.execute(
            "SELECT var_name, var_value, last_updated FROM variables "
            "WHERE project_id = ?",
            (project_id,)
        )
        results = cursor.fetchall()

        variables = {}
        for row in results:
            # 反序列化每个变量的值
            try:
                value = json.loads(row['var_value'])
            except json.JSONDecodeError:
                value = row['var_value']

            variables[row['var_name']] = {
                'value': value,
                'last_updated': row['last_updated']
            }

        return jsonify(variables), 200
    except sqlite3.Error as err:
        return jsonify({'error': str(err)}), 500
    finally:
        conn.close()

@app.route('/api/<project_id>/batch_update', methods=['POST'])
def batch_update(project_id):
    """批量更新变量 - 移除了API key验证"""
    data = request.get_json()
    updates = data.get('updates', [])

    if not updates:
        return jsonify({'error': 'No updates provided'}), 400

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cursor = conn.cursor()

        # 验证项目是否存在
        cursor.execute(
            "SELECT 1 FROM projects WHERE project_id = ?",
            (project_id,)
        )
        if not cursor.fetchone():
            return jsonify({'error': 'Project not found'}), 404

        # 更新访问时间
        current_time = time.time()
        cursor.execute(
            "UPDATE projects SET last_accessed = ? WHERE project_id = ?",
            (current_time, project_id)
        )

        # 批量更新变量
        for update in updates:
            var_name = update['var_name']
            var_value = update['var_value']

            # 序列化值
            serialized_value = json.dumps(var_value)

            cursor.execute(
                "INSERT INTO variables (project_id, var_name, var_value, last_updated) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(project_id, var_name) DO UPDATE SET "
                "var_value = excluded.var_value, last_updated = excluded.last_updated",
                (project_id, var_name, serialized_value, current_time)
            )

        conn.commit()
        return jsonify({'status': 'success', 'updated': len(updates)}), 200
    except sqlite3.Error as err:
        return jsonify({'error': str(err)}), 500
    except (TypeError, OverflowError) as err:
        return jsonify({'error': f'Invalid data: {str(err)}'}), 400
    finally:
        conn.close()

@app.route('/api/cleanup', methods=['POST'])
def cleanup_expired_projects():
    admin_key = request.headers.get('X-Admin-Key')
    if admin_key != os.getenv('ADMIN_KEY'):
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cursor = conn.cursor()
        threshold = time.time() - (90 * 24 * 60 * 60)  # 90天前

        # 删除过期的项目和相关变量
        cursor.execute(
            "DELETE FROM variables WHERE project_id IN ("
            "SELECT project_id FROM projects WHERE last_accessed < ?"
            ")",
            (threshold,)
        )

        cursor.execute(
            "DELETE FROM projects WHERE last_accessed < ?",
            (threshold,)
        )

        deleted_count = cursor.rowcount
        conn.commit()

        return jsonify({
            'status': 'success',
            'projects_deleted': deleted_count
        }), 200
    except sqlite3.Error as err:
        return jsonify({'error': str(err)}), 500
    finally:
        conn.close()

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)