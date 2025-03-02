import dash
from dash import dcc, html, dash_table, Input, Output, State
import requests
import numpy as np
import pandas as pd
from datetime import datetime

# API Keys
TBA_API_KEY = "gp83wLsfRqyOSv9XopquJrncuG5Vd7lG5v07o1qKeLazEmp6jNBMfHR1Ec4UFt1R"
HEADERS = {"X-TBA-Auth-Key": TBA_API_KEY}
STATBOTICS_API = "https://api.statbotics.io/v3/team/{team_key}"

# Dash App
app = dash.Dash(__name__)
server = app.server

# Cache for event data
event_cache = {}

def fetch_events():
    url = "https://www.thebluealliance.com/api/v3/events/2025/simple"
    events = requests.get(url, headers=HEADERS).json()
    return [{"label": event["name"], "value": event["key"]} for event in events if event["start_date"] <= datetime.today().strftime('%Y-%m-%d')]

def fetch_event_data(event_key):
    if event_key in event_cache:
        return event_cache[event_key]
    
    match_url = f"https://www.thebluealliance.com/api/v3/event/{event_key}/matches"
    matches = requests.get(match_url, headers=HEADERS).json()
    
    teams_url = f"https://www.thebluealliance.com/api/v3/event/{event_key}/teams/simple"
    teams = requests.get(teams_url, headers=HEADERS).json()
    
    event_cache[event_key] = {"matches": matches, "teams": teams}
    return event_cache[event_key]

def fetch_epa_data(event_key):
    try:
        data = fetch_event_data(event_key)
        teams_data = data["teams"]
        if not teams_data:
            return {}
        
        team_numbers = [team["team_number"] for team in teams_data]
        epa_data = {}
        
        for team in team_numbers:
            statbotics_url = f"https://api.statbotics.io/v3/team/{team}"
            response = requests.get(statbotics_url)
            if response.status_code == 200:
                team_epa_data = response.json()
                if "norm_epa" in team_epa_data and "current" in team_epa_data["norm_epa"]:
                    epa_data[team] = round(team_epa_data["norm_epa"]["current"], 1)
        
        return epa_data
    except Exception as e:
        print(f"Error fetching EPA data: {e}")
        return {}

def calculate_team_metrics(event_key):
    data = fetch_event_data(event_key)
    matches = [match for match in data["matches"] if match.get("comp_level") == "qm"]  # Only qualification matches
    teams = {team['team_number']: idx for idx, team in enumerate(data['teams'])}
    num_teams = len(teams)
    A, b_opr, b_auto, b_teleop = [], [], [], []
    
    for match in matches:
        if "score_breakdown" not in match or match["score_breakdown"] is None:
            continue
        
        red_teams = [int(team[3:]) for team in match["alliances"]["red"]["team_keys"]]
        blue_teams = [int(team[3:]) for team in match["alliances"]["blue"]["team_keys"]]
        
        red_score, blue_score = match["alliances"]["red"].get("score", 0), match["alliances"]["blue"].get("score", 0)
        auto_red, auto_blue = match["score_breakdown"]["red"].get("autoCoralCount", 0), match["score_breakdown"]["blue"].get("autoCoralCount", 0)
        teleop_red, teleop_blue = match["score_breakdown"]["red"].get("teleopCoralCount", 0), match["score_breakdown"]["blue"].get("teleopCoralCount", 0)
        
        row_red = [1 if team in red_teams else 0 for team in teams]
        row_blue = [1 if team in blue_teams else 0 for team in teams]
        
        A.extend([row_red, row_blue])
        b_opr.extend([red_score, blue_score])
        b_auto.extend([auto_red, auto_blue])
        b_teleop.extend([teleop_red, teleop_blue])
    
    A, b_opr, b_auto, b_teleop = np.array(A), np.array(b_opr), np.array(b_auto), np.array(b_teleop)
    x_opr = np.linalg.lstsq(A, b_opr, rcond=None)[0] if len(A) else np.zeros(num_teams)
    x_auto = np.linalg.lstsq(A, b_auto, rcond=None)[0] if len(A) else np.zeros(num_teams)
    x_teleop = np.linalg.lstsq(A, b_teleop, rcond=None)[0] if len(A) else np.zeros(num_teams)
    
    epa_data = fetch_epa_data(event_key)
    
    return {
        team: {
            "OPR": round(x_opr[idx], 2),
            "Auto Coral": round(x_auto[idx], 2),
            "Teleop Coral": round(x_teleop[idx], 2),
            "EPA": epa_data.get(team, 0)
        } for team, idx in teams.items()
    }

app.layout = html.Div([
    dcc.Dropdown(id='event_dropdown', options=fetch_events(), placeholder='Select an Event'),
    html.Button('Fetch Data', id='fetch_btn', n_clicks=0),
    dash_table.DataTable(
        id='results_table',
        columns=[
            {"name": "#", "id": "Row", "type": "numeric"},
            {"name": "Team", "id": "Team", "type": "numeric"},
            {"name": "OPR", "id": "OPR", "type": "numeric"},
            {"name": "Auto Coral", "id": "Auto Coral", "type": "numeric"},
            {"name": "Teleop Coral", "id": "Teleop Coral", "type": "numeric"},
            {"name": "EPA", "id": "EPA", "type": "numeric"}
        ],
        sort_action="native",
        style_table={'width': '100%'},  # Ensures table spans full width
        style_cell={  
            'textAlign': 'center',
            'padding': '10px',
            'whiteSpace': 'normal'
        },
        style_data_conditional=[
            {"if": {"column_id": "Row"}, "width": "2%"},
            {"if": {"column_id": "Team"}, "width": "19%"},
            {"if": {"column_id": "OPR"}, "width": "19%"},
            {"if": {"column_id": "Auto Coral"}, "width": "19%"},
            {"if": {"column_id": "Teleop Coral"}, "width": "19%"},
            {"if": {"column_id": "EPA"}, "width": "19%"},
        ],
        style_header={
            'fontWeight': 'bold',
            'textAlign': 'center',
            'backgroundColor': 'lightgrey'
        }
    ),
    html.Div(id='match_results_container')
])

@app.callback(
    Output('results_table', 'data'),
    Input('fetch_btn', 'n_clicks'),
    Input('event_dropdown', 'value')
)
def update_table(n_clicks, event_key):
    if not event_key:
        return []
    team_metrics = calculate_team_metrics(event_key)
    return [{"Row": idx + 1, "Team": team, **metrics} for idx, (team, metrics) in enumerate(team_metrics.items())]

if __name__ == "__main__":
    app.run(debug=True)
