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


def calculate_total_ascent(route_data):
    """计算路线的累计爬升
    
    参数:
    route_data: 包含海拔信息的路线坐标点列表
    
    返回:
    float: 累计爬升高度(米)
    """
    MIN_ELEVATION_DIFF = 10  # 最小高度差阈值（米）
    SMOOTHING_WINDOW = 5    # 平滑窗口大小
    NOISE_THRESHOLD = 5     # 噪声阈值（米）
    
    if len(route_data) < 2: 
        return 0
        
    # 1. 首先进行移动平均平滑处理
    smoothed_elevations = []
    for i in range(len(route_data)):
        start_idx = max(0, i - SMOOTHING_WINDOW // 2)
        end_idx = min(len(route_data), i + SMOOTHING_WINDOW // 2 + 1)
        window = [route_data[j]["elevation"] for j in range(start_idx, end_idx)]
        smoothed_elevations.append(sum(window) / len(window))
    
    total_ascent = 0
    current_climb = 0
    last_valid_elevation = smoothed_elevations[0]
    
    for i in range(1, len(smoothed_elevations)):
        elevation_diff = smoothed_elevations[i] - last_valid_elevation
        
        # 2. 过滤噪声
        if abs(elevation_diff) < NOISE_THRESHOLD:
            continue
            
        # 3. 处理有效的高度变化
        if elevation_diff > 0:
            current_climb += elevation_diff
        else:
            if current_climb >= MIN_ELEVATION_DIFF:
                total_ascent += current_climb
            current_climb = 0
        
        last_valid_elevation = smoothed_elevations[i]
    
    # 处理最后一段上升（如果有）
    if current_climb >= MIN_ELEVATION_DIFF:
        total_ascent += current_climb
        
    return total_ascent


def determine_route_type(name):
    """
    根据路线名称判断路线类型
    
    参数:
    name: 路线名称
    
    返回:
    string: 路线类型 ('loop'环线, 'outAndBack'往返, 'pointToPoint'穿越, 'other'其他)
    """
    name_lower = name.lower()
    if 'loop' in name_lower or '环线' in name_lower:
        return "loop"
    elif ('out and back' in name_lower or '折返' in name_lower or 
          'outback' in name_lower):
        return "outAndBack"
    elif ('point to point' in name_lower or '穿越' in name_lower or 
          'pointtopoint' in name_lower):
        return "pointToPoint"
    else:
        return "other"


def determine_route_type_by_coordinates(coordinates):
    """
    根据路线坐标点判断路线类型
    
    参数:
    coordinates: 路线坐标点列表
    
    返回:
    string: 路线类型 ('loop'环线, 'outAndBack'往返, 'pointToPoint'穿越, 'other'其他)
    """
    if not coordinates or len(coordinates) < 2:
        return "other"

    start_point = (coordinates[0]["latitude"], coordinates[0]["longitude"])
    end_point = (coordinates[-1]["latitude"], coordinates[-1]["longitude"])

    # 计算关键距离
    start_end_distance = geodesic(start_point, end_point).kilometers
    print(f"起点和终点之间的距离: {start_end_distance:.2f} 公里")
    total_length = calculate_route_length(coordinates)

    # 如果起终点非常接近
    if start_end_distance < total_length * 0.1:  # 起终点距离小于总长度的10%
        # 找到路线中点
        mid_index = len(coordinates) // 2
        mid_point = (coordinates[mid_index]["latitude"], coordinates[mid_index]["longitude"])
        
        # 计算中点到起点的距离
        mid_to_start = geodesic(start_point, mid_point).kilometers
        
        # 如果中点到起点的距离接近总长度的一半，很可能是折返路线
        if abs(mid_to_start * 2 - total_length) < total_length * 0.3:
            return "outAndBack"
        # 否则判定为环线
        else:
            return "loop"
    
    # 如果起终点距离较远，则可能是穿越路线
    return "pointToPoint"


def determine_features(name):
    """
    根据路线名称识别路线特征
    
    参数:
    name: 路线名称
    
    返回:
    list: 路线特征列表，包含各种特征标签
    """
    features = []
    feature_keywords = {
        "瀑|瀑布|waterfall": "waterfall",
        "湖|lake": "lake",
        "岭|梁|峰|山|mountain": "mountain",
        "林|森林|forest": "forest",
        "沟|溪|河|river": "river",
        "峡|峡谷|canyon": "canyon",
        "洞|cave": "cave",
        "海滩|beach": "beach",
        "城市景观|cityview": "cityView",
        "野生动物|wildlife": "wildlife",
        "历史|historical": "historical",
        "露营|camping": "camping",
        "宠物友好|petfriendly": "petFriendly",
        "家庭友好|familyfriendly": "familyFriendly",
        "秘|隐秘|hidden": "hidden",
        "景|壮观景色|epicview": "epicView"
    }

    for keywords, feature in feature_keywords.items():
        if any(re.search(f".*{keyword}.*", name, re.IGNORECASE) for keyword in keywords.split('|')):
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
    """
    计算路线总长度
    
    参数:
    coordinates: 路线坐标点列表，每个点包含经纬度信息
    
    返回:
    float: 路线总长度(单位：公里)
    """
    length = 0
    for i in range(1, len(coordinates)):
        start = (coordinates[i - 1]["latitude"], coordinates[i - 1]["longitude"])
        end = (coordinates[i]["latitude"], coordinates[i]["longitude"])
        length += geodesic(start, end).kilometers
    return length


def parse_kml_file(kml_file):
    """
    解析单个KML文件，提取路线信息
    
    参数:
    kml_file: KML文件路径
    
    返回:
    dict: 包含路线完整信息的字典，包括名称、描述、坐标等
    """
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
                            print(f"设置上升高度: {route_metadata['total_ascent']}米")
                        if 'descent' in name:
                            route_metadata["total_descent"] = float(data.value)
                            print(f"设置下降高度: {route_metadata['total_descent']}米")
                        if 'time' in name or 'duration' in name:
                            route_metadata["estimated_time"] = float(data.value)
                            print(f"设置预计时间: {route_metadata['estimated_time']}小时")
                        if 'mileage' in name:
                            route_metadata["distance"] = float(data.value)/1000
                            print(f"设置距离: {route_metadata['distance']}公里")
                        if 'difficulty' in name:
                            route_metadata["difficulty"] = data.value
                            print(f"设置难度: {route_metadata['difficulty']}")
                else:
                    pass
            except Exception as e:
                # 继续执行，不中断处理
                pass
        else:
            pass

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
    elevation_change = route_metadata["total_ascent"] if route_metadata["total_ascent"] else calculate_total_ascent(route_data)

    # 使用新公式计算预计时间（小时）
    estimated_time = length / 4 + elevation_change / 250
    
    difficulty = route_metadata["difficulty"] if route_metadata["difficulty"] else determine_difficulty(length,
                                                                                                    elevation_change,
                                                                                                    estimated_time)

    # 添加难度等级的中文映射
    difficulty_cn = {
        'easy': '轻松',
        'moderate': '进阶',
        'hard': '困难',
        'expert': '超难'
    }
    
    # 检查description是否包含坐标信息的HTML
    if (route_metadata["description"] and 
        ("<div>经度" in route_metadata["description"] or 
         "<div>纬度" in route_metadata["description"])):
        # 如果是坐标信息，则使用自动生成的描述
        description = f"这是一条长度为{length:.1f}公里的{difficulty_cn.get(difficulty, '未知')}级别徒步路线，累计爬升{elevation_change:.0f}米，预计完成时间约{estimated_time:.1f}小时。"
    else:
        description = route_metadata["description"] if route_metadata["description"] else (
            f"这是一条长度为{length:.1f}公里的{difficulty_cn.get(difficulty, '未知')}级别徒步路线，累计爬升{elevation_change:.0f}米，预计完成时间约{estimated_time:.1f}小时。")
    print(f"\n路线描述: {description}")

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
        "estimatedTime": estimated_time * 3600,
        "rating": 5
    }

    return route_info


def generate_csv_from_kml_folder():
    """
    处理KML文件夹中的所有KML文件，生成CSV和JSON格式的路线数据
    
    功能：
    1. 遍历KML文件夹
    2. 解析每个KML文件
    3. 整合所有路线数据
    4. 生成CSV和JSON输出文件
    """
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
