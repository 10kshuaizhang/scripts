import os
import pandas as pd
from datetime import datetime
import re
from fastkml import kml
from shapely.geometry import Point, LineString
from geopy.distance import geodesic

# 配置参数
kml_folder_path = './kml'  # 设置 KML 文件夹路径
output_csv_file = 'hiking_routes_kml.csv'  # 设置输出的 CSV 文件名


# 复用parse2.py中的函数
def determine_route_type(name):
    # 与parse2.py中相同
    if 'loop' or '环线' in name.lower():
        return "loop"
    elif 'out and back' or '折返' in name.lower() or 'outback' in name.lower():
        return "outAndBack"
    elif 'point to point' or '穿越' in name.lower() or 'pointtopoint' in name.lower():
        return "pointToPoint"
    else:
        return "other"


def determine_features(name):
    # 与parse2.py中相同
    features = ["mountain"]
    feature_keywords = {
        "瀑布|waterfall": "waterfall",
        "湖|lake": "lake",
        "山|mountain": "mountain",
        "森林|forest": "forest",
        "河|river": "river",
        "峡谷|canyon": "canyon",
        "洞穴|cave": "cave",
        "海滩|beach": "beach",
        "城市景观|cityview": "cityView",
        "野生动物|wildlife": "wildlife",
        "历史|historical": "historical",
        "露营|camping": "camping",
        "宠物友好|petfriendly": "petFriendly",
        "家庭友好|familyfriendly": "familyFriendly",
        "隐秘|hidden": "hidden",
        "壮观景色|epicview": "epicView"
    }

    for keywords, feature in feature_keywords.items():
        if any(re.search(keyword, name, re.IGNORECASE) for keyword in keywords.split('|')):
            if feature not in features:
                features.append(feature)
    return features


def determine_difficulty(d, h, t):
    """
    计算运动强度并返回难度等级
    
    参数:
    d: 距离(km)
    h: 海拔变化(m) 
    t: 预计时间(h)
    
    返回:
    difficulty: 难度等级 ('easy', 'moderate', 'hard', 'expert')
    """
    # 基础参数
    r = 60  # 静息心率
    m = 5   # 默认负重(kg)
    M = 70  # 默认体重(kg)
    H = 1.75  # 默认身高(m)
    
    # 单位转换
    d = d * 1000  # 转换为米
    t = t * 3600  # 转换为秒
    
    # 根据论文公式计算总心跳数
    S = 13 * (
        60 * r * t +
        1587.6 * d +
        23709.6 * h +
        100.8 * m * t +
        (201 / (H * H)) * M * t -
        4049.4 * t
    ) / 50000
    
    # 计算储备总心跳
    reserve_heartbeats = S - (r * t / 60)
    
    # 计算最大储备总心跳
    max_hr = 220 - 30  # 最大心率(按25岁计算)
    max_reserve = (max_hr - r) * t / 60
    
    # 计算储备总心跳百分比
    reserve_percentage = (reserve_heartbeats / max_reserve) * 100
    
    # 根据论文表1的分级标准判断难度
    if reserve_percentage < 35:
        return 'easy'
    elif reserve_percentage < 60:
        return 'moderate'
    elif reserve_percentage < 80:
        return 'hard'
    else:
        return 'expert'


def calculate_route_length(coordinates):
    # 与parse2.py中相同
    length = 0
    for i in range(1, len(coordinates)):
        start = (coordinates[i - 1]["latitude"], coordinates[i - 1]["longitude"])
        end = (coordinates[i]["latitude"], coordinates[i]["longitude"])
        length += geodesic(start, end).kilometers
    return length


def parse_kml_file(kml_file):
    print(f"\n处理KML文件: {kml_file}")

    with open(kml_file, 'rb') as f:
        doc = f.read()
        print(f"成功读取KML文件，大小: {len(doc)} 字节")

    k = kml.KML()
    k = k.from_string(doc)
    print("KML文档解析成功")

    route_data = []
    route_metadata = {
        "name": None,
        "description": None,
        "total_ascent": 0,
        "total_descent": 0,
        "estimated_time": None,
        "distance": None,
        "difficulty": None
    }

    def process_features(feature):
        # 提取名称和描述
        if hasattr(feature, 'name') and route_metadata["name"] is None:
            route_metadata["name"] = feature.name
        if hasattr(feature, 'description') and route_metadata["description"] is None:
            route_metadata["description"] = feature.description

        # 处理扩展数据
        if hasattr(feature, 'extended_data') and feature.extended_data:
            try:
                if hasattr(feature.extended_data, 'elements') and feature.extended_data.elements:
                    for data in feature.extended_data.elements:
                        name = data.name.lower()
                        if 'ascent' in name:
                            route_metadata["total_ascent"] = float(data.value)
                        elif 'descent' in name:
                            route_metadata["total_descent"] = float(data.value)
                        elif 'time' in name or 'duration' in name:
                            route_metadata["estimated_time"] = float(data.value)
                        elif 'distance' in name or 'length' in name:
                            route_metadata["distance"] = float(data.value)
                        elif 'difficulty' in name:
                            route_metadata["difficulty"] = data.value
            except Exception as e:
                print(f"处理扩展数据时出错: {str(e)}")
                # 继续执行，不中断处理

        # 原有的几何数据处理代码...
        if hasattr(feature, 'features'):
            try:
                for f in feature.features:
                    process_features(f)
            except Exception as e:
                print(f"处理子特征时出错: {str(e)}")

        if hasattr(feature, 'geometry') and feature.geometry:
            try:
                geometry_type = feature.geometry.__class__.__name__
                if geometry_type == 'LineString':
                    coords = list(feature.geometry.coords)
                    for coord in coords:
                        route_data.append({
                            "longitude": coord[0],
                            "latitude": coord[1],
                            "elevation": coord[2] if len(coord) > 2 else 0
                        })
            except Exception as e:
                print(f"处理几何数据时出错: {str(e)}")

    # 处理文档...
    try:
        for feature in k.features:
            process_features(feature)
    except Exception as e:
        print(f"解析KML文件时出错: {str(e)}")
        return None

    # 使用提取的元数据更新route_info
    file_name = os.path.basename(kml_file).split('.')[0]
    length = route_metadata["distance"] if route_metadata["distance"] else calculate_route_length(route_data)
    elevation_change = route_metadata["total_ascent"] if route_metadata["total_ascent"] else (
            max(p["elevation"] for p in route_data) - min(p["elevation"] for p in route_data))

    t = length / 4 + elevation_change / 250
    difficulty = route_metadata["difficulty"] if route_metadata["difficulty"] else determine_difficulty(length,
                                                                                                        elevation_change,
                                                                                                        t)

    description = route_metadata["description"] if route_metadata["description"] else (
        f"这是一条长度为{length:.1f}km的徒步路线，高度变化{elevation_change:.0f}米。")

    name = route_metadata["name"] if route_metadata["name"] else file_name

    # 更新route_info的返回值...
    route_type = determine_route_type(name)
    if route_type == "other":
        route_type = determine_route_type_by_coordinates(route_data)

    route_info = {
        "description": description,
        "features": determine_features(name),
        "updatedAt": datetime.now().isoformat(),
        "coordinates": route_data,
        "elevation": elevation_change,
        "difficulty": difficulty,
        "name": name,
        "objectId": None,
        "createdAt": datetime.now().isoformat(),
        "type": route_type,
        "reviewCount": 0,
        "status": "open",
        "thumbnailImage": "https://example.com/default.jpg",
        "length": length,
        "estimatedTime": t * 3600,
        "rating": 5
    }

    return route_info


def determine_route_type_by_coordinates(coordinates):
    # 与parse2.py中相同
    if not coordinates or len(coordinates) < 2:
        return "other"

    start_point = (coordinates[0]["latitude"], coordinates[0]["longitude"])
    end_point = (coordinates[-1]["latitude"], coordinates[-1]["longitude"])

    start_end_distance = geodesic(start_point, end_point).kilometers
    total_length = calculate_route_length(coordinates)

    if start_end_distance < total_length * 0.1:
        return "loop"
    elif abs(start_end_distance * 2 - total_length) < total_length * 0.3:
        return "outAndBack"
    else:
        return "pointToPoint"


def generate_csv_from_kml_folder():
    if not os.path.exists(kml_folder_path):
        os.makedirs(kml_folder_path)
        print(f"创建文件夹: {kml_folder_path}")
        return

    rows = []
    json_data = []

    for file_name in os.listdir(kml_folder_path):
        if file_name.endswith('.kml'):
            kml_file_path = os.path.join(kml_folder_path, file_name)
            route_info = parse_kml_file(kml_file_path)
            if route_info:
                # 创建不包含coordinates的数据副本
                display_info = {k: v for k, v in route_info.items() if k != 'coordinates'}
                rows.append(route_info)
                json_route = {k: v for k, v in route_info.items()
                            if k not in ['objectId', 'createdAt', 'updatedAt']}
                json_data.append(json_route)
                # 打印当前路线的信息
                print("\n路线信息:")
                for key, value in display_info.items():
                    print(f"{key}: {value}")

    if not rows:
        print("没有找到有效的KML文件")
        return

    # 生成CSV文件
    field_types = {
        "description": "string",
        "features": "array",
        "updatedAt": "date",
        "coordinates": "array",
        "elevation": "number",
        "difficulty": "string",
        "name": "string",
        "objectId": "string",
        "createdAt": "date",
        "type": "string",
        "reviewCount": "int",
        "status": "string",
        "thumbnailImage": "string",
        "length": "number",
        "estimatedTime": "number",
        "rating": "number"
    }

    # 创建不包含coordinates的DataFrame
    display_rows = [{k: v for k, v in row.items() if k != 'coordinates'} for row in rows]
    df = pd.DataFrame(display_rows)

    # 打印DataFrame内容
    print("\nCSV文件内容预览:")
    print(df.to_string())

    # 保存完整数据到CSV
    df_full = pd.DataFrame(rows)
    with open(output_csv_file, 'w', encoding='utf-8') as f:
        f.write(','.join(field_types[col] for col in df_full.columns) + '\n')
        f.write(','.join(df_full.columns) + '\n')

    df_full.to_csv(output_csv_file, mode='a', header=False, index=False, encoding='utf-8')
    print(f"\nCSV 文件已生成: {output_csv_file}")

    # 生成JSON文件
    output_json_file = 'hiking_routes_kml.json'
    import json
    with open(output_json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"JSON 文件已生成: {output_json_file}")


if __name__ == '__main__':
    generate_csv_from_kml_folder()
