# Gurobi 7.0.1 is installed in /Library/gurobi701/mac64
from gurobipy import *
from string import *
import numpy as np
import pandas as pd

# Load in match pairings, which will be represented as a list of tuples 
matchups = pd.read_excel('matchups.xlsx')
# Load in values associated with each team. The value of team x is 
# accessed as follows: teamvals.loc[x][1]
teamvals = pd.read_excel('teamvals.xlsx')
weeks = range(0, 17)
timeslots = range(0, 6)

# To get from index to triple:
# i -> (i1,i2,i3), where i1 = (i>=16), i2 = (i%16)/4,and i3 = i%4
# i1 indicates conference. 0: AFC, 1: NFC
# i2 indicates division. 0: East, 1: North, 2: South, 3: West
# i3 indicates rank within division. 0: First, 1: Second, 2: Third, 3: Fourth
# it = (i1, i2, i3) = ((i >= 16) + 0, (i%16)/4, i%4)
# jt = (j1, j2, j3) = ((j >= 16) + 0, (j%16)/4, j%4)

model = Model('NFL Schedule')
decvar = {}
num_matches = len(matchups)

# tm_opp_dict is a dictionary where the keys are teams, and the value is the 
# list of teams that that team has to play against
tm_opp_dict = {}
for index in xrange(0, num_matches):
    i, j, h = matchups.loc[index] # 256 rows
    if i in tm_opp_dict: tm_opp_dict[i].add((j, h))
    else: tm_opp_dict[i] = {(j, h)}
    if j in tm_opp_dict: tm_opp_dict[j].add((i, abs(h-1)))
    else: tm_opp_dict[j] = {(i, abs(h-1))}

# Decision variables: X, i, j, w, t, h
# i: team 1, j: team 2, w: week, t: timeslot, h: home/road (wrt team 1) 
for tm in tm_opp_dict:
    for opp in tm_opp_dict[tm]:
        (opp_tm, h) = opp
        gm_inst = 0
        for w in weeks:
            for t in timeslots:
                dv = model.addVar(vtype=GRB.BINARY,
                name="X-{},{},{},{},{}".format(tm, opp_tm, w, t, h))
                decvar[tm, opp_tm, w, t, h] = dv
                gm_inst += dv
        # Constraint 1: Each game is played once
        model.addConstr(gm_inst == 1, "gm_inst-{},{}".format(tm, opp))

for tm in tm_opp_dict:
    for w in weeks:
        gm_pw = 0
        for opp in tm_opp_dict[tm]:
            (opp_tm, h) = opp
            for t in timeslots:
                gm_pw += decvar[tm, opp_tm, w, t, h]
        # Constraint 2a): Each team plays once a week for the first 3 weeks
        # and for the last 5 weeks
        if w in {0, 1, 2, 12, 13, 14, 15, 16}:
            model.addConstr(gm_pw == 1, "gm_pw-{},{}".format(tm, w))
        # Constraint 2b): Each team plays at most once a week for the 
        # remaining weeks
        else: # weeks 3, 4, 5, 6, 7, 8, 9, 10, 11 (0-indexed)
            model.addConstr(gm_pw <= 1, "gm_pw-{},{}".format(tm, w))

for w in weeks:
    for t in timeslots:
        ts_inst = 0
        for tm in tm_opp_dict:
            for opp in tm_opp_dict[tm]:
                (opp_tm, h) = opp
                ts_inst += decvar[tm, opp_tm, w, t, h]
        # Constraint 3: Each timeslot has an upper and lower bound on the 
        # no. of games that can be played
        if (t == 0 or t == 4 or t==5):
            model.addConstr(ts_inst == 2, "ts_inst-{},{}".format(w, t))
        elif t == 1:
            model.addConstr(ts_inst <= 20, "ts_inst_hi-{},{}".format(w, t))
            model.addConstr(ts_inst >= 12, "ts_inst_lo-{},{}".format(w, t))
        else:
            model.addConstr(ts_inst <= 4, "ts_inst_hi-{},{}".format(w, t))
            model.addConstr(ts_inst >= 2, "ts_inst_lo-{},{}".format(w, t))

for tm in tm_opp_dict:
    # shortweeks = 0
    for w in weeks[1:]:
        thurs = 0
        prev_mons = 0
        thurs_r = 0
        prev_suns_r = 0
        for opp in tm_opp_dict[tm]:
            (opp_tm, h) = opp
            thurs += decvar[tm, opp_tm, w, 0, h]
            if h == 1:
                thurs_r += decvar[tm, opp_tm, w, 0, h]
                for t in range(1, 5):
                    prev_suns_r += decvar[tm, opp_tm, w-1, t, h]
            prev_mons += decvar[tm, opp_tm, w-1, 5, h]
        # Constraint 4: Teams are not allowed to play on Thursday if their 
        # previous game was on the previous Monday
        model.addConstr(thurs + prev_mons <= 1, "th_prev_mo-{},{}".format(tm, w))
        # Constraint 7**: No team has to play consecutive away games that are 
        # also separated by a short week
        model.addConstr(prev_suns_r <= (1 - thurs_r), "th_r_prev_sun_r-{}{}".format(tm, w))

for tm in tm_opp_dict:
    for w in weeks[0:15]:
        hg = 0
        for wk in weeks[w:w+3]:
            for opp in tm_opp_dict[tm]:
                (opp_tm, h) = opp
                if h == 1: 
                    for t in timeslots:
                        hg += decvar[tm, opp_tm, wk, t, h]
        # Constraint 5a): No more than 3 consecutive road games
        model.addConstr(hg >= 1, "hg_lo-{},{}".format(tm, w))
        # Constraint 5b): No more than 3 consecutive home games
        model.addConstr(hg <= 2, "hg_hi-{},{}".format(tm, w))

for tm in tm_opp_dict:
    th_inst = 0
    for opp in tm_opp_dict[tm]:
        (opp_tm, h) = opp
        for w in weeks:
            th_inst += decvar[tm, opp_tm, w, 0, h]
        # Constraint 6: Each team plays at most 2 Thursday game per season
        # - The original idea was to constrain each team to play at most
        # 1 Thursday game per season, but this conflicted with the previous 
        # constraints and led to there being no feasible solutions. 
    model.addConstr(th_inst <= 2, "th_inst-{}".format(tm))

# Maximization objective:
# 1) Add in cost

obj = 0
for index in xrange(0, num_matches):
    i, j, h = matchups.loc[index]
    for w in weeks: # 17 weeks
        for t in timeslots: # 6 timeslots
            coeff = teamvals.loc[i][1] + teamvals.loc[j][1]
            if t == 0: coeff *= 1.5
            elif t == 3 or t == 5: coeff *= 1.2
            elif t == 4: coeff *= 2 
            obj += decvar[i, j, w, t, h]*coeff

model.setObjective(obj, GRB.MAXIMIZE)
model.optimize()

# for v in model.getVars(): # 52020 rows
#     print v.getAttr("Varname"), v.getAttr("X") 

# Parse results into matrix
# 105 = 1 + 1 + 17*6 + 1
results = np.empty(shape=(256, 105))
for index in xrange(0, num_matches):
    i, j, h = matchups.loc[index]
    results[index][0] = i
    results[index][1] = j
    for w in weeks: # 17 weeks
        for t in timeslots: # 6 timeslots
            val = decvar[i, j, w, t, h].X
            results[index][w*6 + t + 2] = val
    results[index][104] = h

# Convert np array to pd DataFrame
df = pd.DataFrame(results)
# Write df to excel file 
df.to_excel('output.xlsx')