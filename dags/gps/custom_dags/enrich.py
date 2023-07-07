# Monthly DAG
from datetime import datetime
from airflow import DAG
from airflow.utils.task_group import TaskGroup
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor
from airflow.models import Variable
from minio import Minio
from gps import CONFIG
from gps.common.cleaning import (
    clean_base_sites,
    cleaning_esco,
    cleaning_ihs,
    cleaning_alarm,
    cleaning_traffic,
    cleaning_cssr,
    cleaning_congestion,
)
from gps.common.enrich import oneforall, get_last_ofa
from gps.common.alerting import alert_failure
from gps.common.rwminio import save_minio, get_latest_file
from gps.common.rwpg import write_pg


MINIO_ENDPOINT = Variable.get('minio_host')
MINIO_ACCESS_KEY = Variable.get('minio_access_key')
MINIO_SECRET_KEY = Variable.get('minio_secret_key')

SMTP_HOST = Variable.get('smtp_host')
SMTP_PORT = Variable.get('smtp_port')
SMTP_USER = Variable.get('smtp_user')

PG_SAVE_HOST = Variable.get('pg_save_host')
PG_SAVE_DB = Variable.get('pg_save_db')
PG_SAVE_USER = Variable.get('pg_save_user')
PG_SAVE_PASSWORD = Variable.get('pg_save_password')

DATE = "{{data_interval_start.strftime('%Y-%m-%d')}}"
CLIENT = Minio( MINIO_ENDPOINT,
        access_key= MINIO_ACCESS_KEY,
        secret_key= MINIO_SECRET_KEY,
        secure=False)

def on_failure(context):
    """
    Function to handle task failure
    """
    params = {
        "host": SMTP_HOST,
        "port": SMTP_PORT,
        "user": SMTP_USER,
        "task_id": context["task"].task_id,
        "dag_id": context["task"].dag_id,
        "exec_date": context.get("ts"),
        "exception": context.get("exception"),
    }
    if "cleaning_bdd" in params["task_id"]:
        params["type_fichier"] = "BASE_SITES"
    elif "cleaning_esco" in params["task_id"]:
        params["type_fichier"] = "OPEX_ESCO"
    elif "cleaning_ihs" in params["task_id"]:
        params["type_fichier"] = "OPEX_IHS"
    else:
        raise RuntimeError("Can't get file type")
    alert_failure(**params)

def check_file(**kwargs ):
    """
    check if file exists
    """
    table_obj = next((table for table in CONFIG["tables"] if table["name"] == kwargs['table_type'] ), None)
    date_parts = kwargs["date"].split("-")
    filename = get_latest_file(client=kwargs["client"], bucket=table_obj["bucket"], prefix=f"{table_obj['folder']}/{table_obj['folder']}_{date_parts[0]}{date_parts[1]}")
    if filename != None:
        return True
    return False

def gen_oneforall(**kwargs):
    data = oneforall(
        CLIENT,
        kwargs["endpoint"],
        kwargs["accesskey"],
        kwargs["secretkey"],
        kwargs["date"],
        kwargs["start_date"],
    )
    if not data.empty:
        save_minio(client=CLIENT, bucket="oneforall", folder=None, date=kwargs["date"], data=data)
    else:
        raise RuntimeError(f"No data for {kwargs['date']}")
def save_in_pg(**kwargs):
    data = get_last_ofa(
        CLIENT,
        kwargs["endpoint"],
        kwargs["accesskey"],
        kwargs["secretkey"],
        kwargs["date"],
    )
    if not data.empty:
        write_pg(
            host=PG_SAVE_HOST,
            database=PG_SAVE_DB,
            user=PG_SAVE_USER,
            password=PG_SAVE_PASSWORD,
            data=data,
            table="oneforall"
        )
    else:
        raise RuntimeError(f"No data for {kwargs['date']}")
 # Set up DAG
with DAG(
    "enrich",
    default_args={
        "depends_on_past": False,
        "email": CONFIG["airflow_receivers"],
        "email_on_failure": True,
        "email_on_retry": False,
        "max_active_run": 1,
        "retries": 0,
    },
    description="clean monthly data",
    schedule_interval="0 0 6 * *",
    start_date=datetime(2023, 1, 6, 0, 0, 0),
    catchup=True,
) as dag:
     # Task group for cleaning tasks
    with TaskGroup("cleaning", tooltip="Tasks for cleaning") as section_cleaning:
        check_bdd_sensor =  PythonSensor(
            task_id= "check_bdd_sensor",
            mode='poke',
            poke_interval= 24* 60 *60,
            timeout = 264 * 60 * 60,
            python_callable= check_file,
            op_kwargs={
                  'client': CLIENT,
                  'table_type': 'BASE_SITES',
                  'date': DATE,
            #     'smtp_host': SMTP_HOST,
            #     'smtp_user': SMTP_USER,
            #     'smtp_port': SMTP_PORT,
            #     'receivers': CONFIG["airflow_receivers"]
            })
        
        clean_base_site = PythonOperator(
            task_id="cleaning_bdd",
            provide_context=True,
            python_callable=clean_base_sites,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            on_failure_callback=on_failure,
            dag=dag,
        )
        check_esco_sensor =  PythonSensor(
            task_id= "check_esco_sensor",
            mode='poke',
            poke_interval= 24* 60 *60,
            timeout = 264 * 60 * 60,
            python_callable= check_file,
            op_kwargs={
                  'client': CLIENT,
                  'table_type': 'OPEX_ESCO',
                  'date': DATE,
            #     'smtp_host': SMTP_HOST,
            #     'smtp_user': SMTP_USER,
            #     'smtp_port': SMTP_PORT,
            #     'receivers': CONFIG["airflow_receivers"]
            })
        clean_opex_esco = PythonOperator(
            task_id="cleaning_esco",
            provide_context=True,
            python_callable=cleaning_esco,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            on_failure_callback=on_failure,
            dag=dag,
        )
        check_ihs_sensor =  PythonSensor(
            task_id= "check_ihs_sensor",
            mode='poke',
            poke_interval= 24* 60 *60,
            timeout = 264 * 60 * 60,
            python_callable= check_file,
            op_kwargs={
                  'client': CLIENT,
                  'table_type': 'OPEX_IHS',
                  'date': DATE,
            #     'smtp_host': SMTP_HOST,
            #     'smtp_user': SMTP_USER,
            #     'smtp_port': SMTP_PORT,
            #     'receivers': CONFIG["airflow_receivers"]
            })
        clean_opex_ihs = PythonOperator(
            task_id="cleaning_ihs",
            provide_context=True,
            python_callable=cleaning_ihs,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            on_failure_callback=on_failure,
            dag=dag,
        )
        # clean_ca_parc = PythonOperator(
        #     task_id='cleaning_ca_parc',
        #     provide_context=True,
        #     python_callable=cleaning_ca_parc,
        #     op_kwargs={'client': CLIENT,
        #                'date': DATE},
        #     dag=dag
        # )
        clean_alarm = PythonOperator(
            task_id="cleaning_alarm",
            provide_context=True,
            python_callable=cleaning_alarm,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            dag=dag,
        )
        clean_trafic = PythonOperator(
            task_id="cleaning_trafic",
            provide_context=True,
            python_callable=cleaning_traffic,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            dag=dag,
        )
        clean_cssr = PythonOperator(
            task_id="cleaning_cssr",
            provide_context=True,
            python_callable=cleaning_cssr,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            dag=dag,
        )
        check_congestion_sensor =  PythonSensor(
            task_id= "check_congestion_sensor",
            mode='poke',
            poke_interval= 24* 60 *60,
            timeout = 264 * 60 * 60,
            python_callable= check_file,
            op_kwargs={
                  'client': CLIENT,
                  'table_type': 'CONGESTION',
                  'date': DATE,
            #     'smtp_host': SMTP_HOST,
            #     'smtp_user': SMTP_USER,
            #     'smtp_port': SMTP_PORT,
            #     'receivers': CONFIG["airflow_receivers"]
            })
        clean_congestion = PythonOperator(
            task_id="cleaning_congestion",
            provide_context=True,
            python_callable=cleaning_congestion,
            op_kwargs={
                "client": CLIENT,
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            dag=dag,
        )
        check_bdd_sensor >> clean_base_site
        check_congestion_sensor >> clean_opex_esco
        check_ihs_sensor >> clean_opex_ihs
        check_congestion_sensor >> clean_congestion
        [clean_alarm, clean_trafic, clean_cssr]

    # Task group for oneforall tasks
    with TaskGroup("oneforall", tooltip="Tasks for generate oneforall") as section_oneforall:
        merge_data = PythonOperator(
            task_id="join_data",
            provide_context=True,
            python_callable=gen_oneforall,
            op_kwargs={
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
                "start_date": "2023-01-06",
            },
            dag=dag,
        )
        save_pg = PythonOperator(
            task_id="save_pg",
            provide_context=True,
            python_callable=save_in_pg,
            op_kwargs={
                "endpoint": MINIO_ENDPOINT,
                "accesskey": MINIO_ACCESS_KEY,
                "secretkey": MINIO_SECRET_KEY,
                "date": DATE,
            },
            dag=dag,
        )
        merge_data >> save_pg
    section_cleaning >> section_oneforall

    # clean_call_drop = PythonOperator(
    #     task_id='cleaning_call_drop',
    #     provide_context=True,
    #     python_callable=cleaning_call_drop,
    #     op_kwargs={'endpoint': MINIO_ENDPOINT,
    #                'accesskey': MINIO_ACCESS_KEY,
    #                'secretkey': MINIO_SECRET_KEY,
    #                'date': DATE},
    #     dag=dag
    # )
    
    