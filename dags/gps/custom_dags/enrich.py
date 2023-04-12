from datetime import datetime
from airflow import DAG
from gps.common.enrich import cleaning_base_site, cleaning_esco, cleaning_ihs
from airflow.operators.python import PythonOperator
from airflow.models import Variable
from gps import CONFIG
from gps.common.alerting import alert_failure



MINIO_ENDPOINT = Variable.get('minio_host')
MINIO_ACCESS_KEY = Variable.get('minio_access_key')
MINIO_SECRET_KEY = Variable.get('minio_secret_key')

SMTP_HOST = Variable.get('smtp_host')
SMTP_PORT = Variable.get('smtp_port')
SMTP_USER = Variable.get('smtp_user')


DATE = "{{data_interval_start.strftime('%Y-%m-%d')}}"

def on_failure(context):
    """
        on failure function
    """
    params = {
        "host" : SMTP_HOST,
        "port" : SMTP_PORT,
        "user": SMTP_USER,
        "task_id" : context['task'].task_id,
        "dag_id" : context['task'].dag_id,
        "exec_date" : context.get('ts') ,
        "exception" : context.get('exception'),

    }
    if "enrich_base_sites" in params['task_id'] :
        params['type_fichier'] = "BASE_SITES"
    elif "enrich_esco" in  params['task_id']:
        params['type_fichier'] = "OPEX_ESCO"
    elif "enrich_ihs" in params['task_id']:
        params['type_fichier'] = "OPEX_IHS"
    else:
        raise RuntimeError("Can't get file type")
    
    alert_failure(**params)

with DAG(
    'enrich',
    default_args={
        'depends_on_past': False,
        'email': CONFIG["airflow_receivers"],
        'email_on_failure': True,
        'email_on_retry': False,
        'max_active_run': 1,
        'retries': 0
    },
    description='clean and enrich monthly data',
    schedule_interval= "0 0 6 * *",
    start_date=datetime(2023, 1, 6, 0, 0, 0),
    catchup=True
) as dag:

    clean_base_site = PythonOperator(
        task_id='enrich_base_sites',
        provide_context=True,
        python_callable=cleaning_base_site,
        op_kwargs={'endpoint': MINIO_ENDPOINT,
                   'accesskey': MINIO_ACCESS_KEY,
                   'secretkey': MINIO_SECRET_KEY,
                   'date': DATE},
        on_failure_callback = on_failure,
        dag=dag
    ),
    clean_opex_esco = PythonOperator(
        task_id='enrich_esco',
        provide_context=True,
        python_callable=cleaning_esco,
        op_kwargs={'endpoint': MINIO_ENDPOINT,
                   'accesskey': MINIO_ACCESS_KEY,
                   'secretkey': MINIO_SECRET_KEY,
                   'date': DATE},
        on_failure_callback = on_failure,
        dag=dag
    ),
    clean_opex_ihs = PythonOperator(
        task_id='enrich_ihs',
        provide_context=True,
        python_callable=cleaning_ihs,
        op_kwargs={'endpoint': MINIO_ENDPOINT,
                   'accesskey': MINIO_ACCESS_KEY,
                   'secretkey': MINIO_SECRET_KEY,
                   'date': DATE},
        on_failure_callback = on_failure,
        dag=dag
    )
    
    [clean_base_site, clean_opex_esco,clean_opex_ihs]
