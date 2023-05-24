import os, sys
import yaml
import importlib
import logging
from itertools import product
from more_itertools import collapse

import torch
import pytorch_lightning as pl
from pytorch_lightning.loggers import WandbLogger, TensorBoardLogger, CMFLogger
from pytorch_lightning.callbacks import ModelCheckpoint, LearningRateMonitor
import wandb

from simple_slurm import Slurm

from .config_utils import handle_config_cases


def find_model(model_set, model_name, model_library):  # M

    # List all modules in the set/ and set/Models directories
    module_list = [
        os.path.splitext(name)[0]
        for name in os.listdir(os.path.join(model_library, model_set, "Models"))
        if name.endswith(".py")
    ]

    # Import all modules in the set/Models directory and find model_name
    imported_module_list = [
        importlib.import_module(".".join([model_set, "Models", module]))
        for module in module_list
    ]
    names = [
        mod
        for mod in imported_module_list
        if model_name
        in getattr(mod, "__all__", [n for n in dir(mod) if not n.startswith("_")])
    ]
    if len(names) == 0:
        print("Couldn't find model or callback", model_name)
        return None
        
    # Return the class of model_name
    model_class = getattr(names[0], model_name)
    logging.info("Model found")
    return model_class


def build_model(model_config):  # M

    model_set = model_config["set"]
    model_name = model_config["name"]
    model_library = model_config["model_library"]
    config_file = model_config["config"]

    logging.info("Building model...")
    model_class = find_model(model_set, model_name, model_library)

    logging.info("Model built")
    return model_class


def get_logger(model_config):  # M

    logger_choice = model_config["logger"]
    if "project" not in model_config.keys(): model_config["project"] = "my_project"
    
    if logger_choice == "wandb":
        logger = WandbLogger(
            project=model_config["project"],
            save_dir=model_config["artifact_library"],
            id=model_config["resume_id"],
        )

    elif logger_choice == "tb":
        logger = TensorBoardLogger(
            name=model_config["project"],
            save_dir=model_config["artifact_library"],
            version=model_config["resume_id"],
        )
    
    elif logger_choice == "cmf":
        #print(model_config["artifact_library"]+"/"+model_config["project"]+"_mlmd")
        logger = CMFLogger(
            mlmd_filename=model_config["artifact_library"]+"/"+model_config["project"]+"_mlmd",
            pipeline_name=model_config["project"],
            pipeline_stage=model_config["set"],
            execution_type=model_config["set"],
            #save_dir=model_config["artifact_library"],
            #version=model_config["resume_id"],
        )

    elif logger_choice == None:
        logger = None

    logging.info("Logger retrieved")
    return logger


def callback_objects(model_config, lr_logger=False):  # M

    callback_list = model_config["callbacks"] if "callbacks" in model_config.keys() else None
    callback_list = handle_config_cases(callback_list)

    model_set = model_config["set"]
    model_library = model_config["model_library"]
    callback_object_list = [
        find_model(model_set, callback, model_library)() for callback in callback_list
    ]

    if lr_logger:
        lr_monitor = LearningRateMonitor(logging_interval="epoch")
        callback_object_list = callback_object_list + [lr_monitor]

    logging.info("Callbacks found")
    return callback_object_list


def build_trainer(model_config, logger):  # M

    fom = model_config["fom"] if "fom" in model_config.keys() else "val_loss"
    fom_mode = model_config["fom_mode"] if "fom_mode" in model_config.keys() else "min"

    print ("Before Initializing Trainer ....... ")
    
    checkpoint_callback = ModelCheckpoint(
        monitor=fom, save_top_k=2, save_last=True, mode=fom_mode
    )


    #gpus = 1 if torch.cuda.is_available() else 0
    gpus = 1
    num_nodes = 2

    # Handle resume condition
    if model_config["resume_id"] is None:
        # The simple case: We start fresh
        trainer = pl.Trainer(
            max_epochs=model_config["max_epochs"],
            #gpus=gpus,
            logger=logger,
            callbacks=callback_objects(model_config)+[checkpoint_callback],
            strategy="ddp",
            accelerator="gpu",
            devices=gpus,
            num_nodes=num_nodes,
        )
    else:
        num_sanity = model_config["sanity_steps"] if "sanity_steps" in model_config else 2
        # Here we assume
        trainer = pl.Trainer(
            resume_from_checkpoint=model_config["checkpoint_path"],
            max_epochs=model_config["max_epochs"],
            #gpus=gpus,
            num_sanity_val_steps=num_sanity,
            logger=logger,
            callbacks=callback_objects(model_config)+[checkpoint_callback],
            strategy="ddp",
            accelerator="gpu",
            devices=gpus,
            num_nodes=num_nodes,
        )

    logging.info("Trainer built")
    print ("After Initializing Trainer ....... ")
    return trainer


def get_resume_id(stage):  # M
    resume_id = stage["resume_id"] if "resume_id" in stage.keys() else None
    return resume_id
