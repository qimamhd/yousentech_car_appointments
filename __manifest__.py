{
 'name':'Yousen Car Care Appointments',
 'version':'13.0.6.74.0',
 'summary':'PPF, tinting and detailing appointment management',
 'category':'Services',
 'author':'Yousen Tech',
 'license':'LGPL-3',
 'depends':['base','web','mail','qimamhd_wo_v3'],
 'data':['security/groups.xml','security/ir.model.access.csv','security/branch_rules.xml','data/sequence.xml','data/cron.xml','views/calendar_action.xml','views/appointment_views.xml','views/installation_check_views.xml','views/installation_order_lock_views.xml','views/feedback_views.xml','data/feedback_data.xml','views/dashboard_action.xml'],
 'qweb':['static/src/xml/calendar.xml','static/src/xml/dashboard.xml'],
 'application':False,
 'installable':True,
}
