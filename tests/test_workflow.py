"""Exercise actual Streamlit reruns and callbacks without a browser driver."""
from pathlib import Path
import copy
import unittest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / 'app.py'


def button(app, label):
    return next(item for item in app.button if item.label == label)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file(APP, default_timeout=20).run()
        button(self.app, 'Try example').click().run()
        self.assertHealthy()

    def assertHealthy(self):
        self.assertEqual([e.message for e in self.app.exception], [])

    def test_dataset_create_rename_delete_undo_redo(self):
        app = self.app
        button(app, '+ Add dataset').click().run()
        self.assertHealthy()
        self.assertEqual(len(app.session_state.datasets), 2)
        second = app.session_state.active_id
        next(x for x in app.text_input if x.label=='Dataset name').set_value('Experiment B').run()
        self.assertEqual(app.session_state.datasets[1]['name'], 'Experiment B')
        button(app, 'Delete dataset').click().run()
        self.assertEqual(len(app.session_state.datasets), 1)
        button(app, 'Undo').click().run()
        self.assertEqual(app.session_state.datasets[1]['name'], 'Experiment B')
        button(app, 'Redo').click().run()
        self.assertEqual(len(app.session_state.datasets), 1)
        self.assertHealthy()

    def test_log_axis_blocks_zero_and_recovers(self):
        app=self.app
        app.selectbox(key='x_scale').set_value('Logarithmic').run()
        self.assertTrue(any('positive' in e.value for e in app.error))
        app.number_input(key='x0').set_value(1.0).run()
        self.assertEqual(app.metric[3].value, 'Ready')
        self.assertHealthy()

    def test_replacement_clears_points_and_history(self):
        app=self.app
        app.session_state.datasets[0]['points']=[[300,300]]
        button(app, '+ Add dataset').click().run()
        app.selectbox(key='example_kind').set_value('Rotated').run()
        button(app, 'Try example').click().run()
        self.assertEqual(app.session_state.image_id,'example-Rotated')
        self.assertEqual(len(app.session_state.datasets),1)
        self.assertEqual(app.session_state.datasets[0]['points'],[])
        self.assertEqual(app.session_state.undo_stack,[])
        self.assertEqual(app.metric[3].value,'Ready')
        self.assertHealthy()

    def test_labels_do_not_change_raw_coordinates(self):
        app=self.app
        app.session_state.datasets[0]['points']=[[507.5,312.5]]
        app.text_input(key='x_label').set_value('Time (s)').run()
        app.text_input(key='y_label').set_value('Current, μA').run()
        self.assertEqual(app.session_state.datasets[0]['points'],[[507.5,312.5]])
        self.assertEqual(app.metric[2].value,'1')
        self.assertHealthy()

    def test_reference_mode_does_not_destroy_data(self):
        app=self.app
        app.session_state.datasets[0]['points']=[[507.5,312.5]]
        button(app,'1 · Pick O').click().run()
        self.assertEqual(app.session_state.mode,'origin')
        self.assertEqual(app.session_state.datasets[0]['points'],[[507.5,312.5]])
        self.assertHealthy()

    def test_table_edits_inverse_transform_and_incomplete_rows(self):
        tail = '''
if '_table_test' in st.session_state:
    delta=st.session_state.pop('_table_test')
    cal,_=current_calibration()
    active=st.session_state.datasets[0]
    values=[cal.pixel_to_data(*p) for p in active['points']]
    st.session_state['_test_editor']=delta
    apply_table(active['id'],'_test_editor',values,cal)
    st.rerun()
'''
        app=AppTest.from_string(APP.read_text(encoding='utf-8')+tail,default_timeout=20).run()
        button(app,'Try example').click().run()
        app.session_state.datasets[0]['points']=[[507.5,312.5]]
        app.session_state['_table_test']={'edited_rows':{0:{'x':6}},'deleted_rows':[],'added_rows':[]}
        app.run()
        px,py=app.session_state.datasets[0]['points'][0]
        self.assertAlmostEqual(px,586.0)
        self.assertAlmostEqual(py,312.5)
        self.assertEqual([e.message for e in app.exception],[])
        rev=app.session_state.revision
        app.session_state['_table_test']={'edited_rows':{},'deleted_rows':[],'added_rows':[{'x':3}]}
        app.run()
        self.assertEqual(app.session_state.revision,rev)
        self.assertEqual(len(app.session_state.datasets[0]['points']),1)
        app.session_state['_table_test']={'edited_rows':{},'deleted_rows':[],'added_rows':[{'x':3,'y':4}]}
        app.run()
        self.assertEqual(len(app.session_state.datasets[0]['points']),2)
        app.session_state['_table_test']={'edited_rows':{},'deleted_rows':[0],'added_rows':[]}
        app.run()
        self.assertEqual(len(app.session_state.datasets[0]['points']),1)
        self.assertEqual([e.message for e in app.exception],[])

    def test_project_roundtrip_preserves_points_labels_and_log_axes(self):
        tail = '''
def _test_roundtrip_callback():
    raw=project_bytes()
    restore_project(raw)
st.button('Test roundtrip',on_click=_test_roundtrip_callback)
'''
        app=AppTest.from_string(APP.read_text(encoding='utf-8')+tail,default_timeout=20).run()
        app.selectbox(key='example_kind').set_value('Logarithmic').run()
        button(app,'Try example').click().run()
        app.session_state.datasets[0]['points']=[[507.5,312.5]]
        original=copy.deepcopy(app.session_state.datasets)
        button(app,'Test roundtrip').click().run()
        self.assertEqual(app.session_state.datasets,original)
        self.assertEqual(app.session_state.x_scale,'Logarithmic')
        self.assertEqual(app.metric[3].value,'Ready')
        self.assertEqual([e.message for e in app.exception],[])


if __name__=='__main__':
    unittest.main(verbosity=2)
