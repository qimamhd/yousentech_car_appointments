{
 'name':'Yousen Car Care Appointments',
 'version':'13.0.2.2.0',
 'summary':'PPF, tinting and detailing appointment management',
 'category':'Services',
 'author':'Yousen Tech',
 'license':'LGPL-3',
 'depends':['base','web','mail','qimamhd_wo_v3'],
 'data':['security/ir.model.access.csv','data/sequence.xml','data/cron.xml','views/calendar_action.xml','views/appointment_views.xml'],
 'qweb':['static/src/xml/calendar.xml'],
 'application':False,
 'installable':True,
}
