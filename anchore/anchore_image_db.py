import json
import re
import os
import shutil
import time
import logging

import anchore_utils

DEVNULL = open(os.devnull, 'wb')

class AnchoreImageDB(object):
    _db_metadata_filename = 'anchore_db_meta.json'
    _logger = logging.getLogger(__name__)

    def __del__(self):
        if self.initialized:
            pass

    @staticmethod
    def exists(path, with_expected_db_version=None):
        """
        Does the db exist, optionally with the expected version
        :param path:
        :param with_expected_db_version:
        :return:
        """
        dbmetafile = os.path.join(path, AnchoreImageDB._db_metadata_filename)

        if not os.path.exists(path) or not os.path.exists(dbmetafile):
            return False

        if with_expected_db_version:
            with open(dbmetafile, 'r') as f:
                json_dict = json.load(f)

            if json_dict['anchore_db_version'] != with_expected_db_version:
                return False
        else:
            return True

    def __init__(self, imagerootdir):
        self.initialized = False
        self.imagerootdir = imagerootdir
        self.version = None
        try:
            from anchore import version as anchore_version_string
            anchore_db_version_string = anchore_version_string
            try:
                patt = re.match("([0-9]+)\.([0-9]+)\.(.*)", anchore_version_string)
                if patt:
                    (major, minor, subminor) = patt.group(1,2,3)
                    anchore_db_version_string = '.'.join([major, minor])
            except Exception as err:
                pass
                
            self.version = {'anchore_version': anchore_version_string, 'db_version': anchore_db_version_string}

            if not os.path.exists(self.imagerootdir):
                raise Exception("anchore DB: image root dir does not exist "+str(imagerootdir))

            # check that the software and DB are same version before continuing
            dbmetafile = '/'.join([self.imagerootdir, "anchore_db_meta.json"])
            if not os.path.exists(dbmetafile):
                with open(dbmetafile, 'w') as OFH:
                    OFH.write(json.dumps({}))

            update = False

            with open(dbmetafile, 'r') as FH:
                json_dict = json.loads(FH.read())

            if 'anchore_version' not in json_dict:
                json_dict['anchore_version'] = anchore_version_string
                update = True
            elif json_dict['anchore_version'] != anchore_version_string:
                json_dict['anchore_version'] = anchore_version_string
                update = True

            if 'anchore_db_version' not in json_dict:
                json_dict['anchore_db_version'] = anchore_db_version_string
                update = True
            elif json_dict['anchore_db_version'] != anchore_db_version_string:
                # Check major version
                local_db_version = json_dict['anchore_db_version']
                db_version_tuple = tuple(local_db_version.split('.'))
                code_version_tuple = tuple(anchore_db_version_string.split('.'))
                if db_version_tuple[0] < code_version_tuple[0]:
                    raise ValueError("Anchore DB version ("+local_db_version + ") cannot be automatically upgraded to this Anchore software version (" + anchore_version_string + ") Please downgrade Anchore to compatible version or remove your Anchore DB and start from a clean install.")
                else:
                    json_dict['anchore_db_version'] = anchore_db_version_string
                    update = True

            if update:
                with open(dbmetafile, 'w') as OFH:
                    OFH.write(json.dumps(json_dict))

        except ValueError as err:
            raise err
        except Exception as err:
            raise err

        self.initialized = True        

    def get_version(self):
        return(self.version)

    def check(self):
        return(self.initialized)

    def is_image_present(self, imageId, imagelist=None):
        thefile = '/'.join([self.imagerootdir, imageId])
        if not os.path.exists(thefile):
            return(False)
        return(True)

    def is_image_analyzed(self, imageId):
        amanifest = self.load_analyzer_manifest(imageId)
        if not amanifest:
            return(False)
        else:
            for a in amanifest.keys():
                try:
                    if amanifest[a]['status'] != "SUCCESS":
                        raise Exception("analyzer ("+str(a)+") not executes/failed")
                except Exception as err:
                    return(False)
        return(True)

    def get_image_list(self):
        ret = {}
        for d in os.listdir(self.imagerootdir):
            if os.path.exists(os.path.join(self.imagerootdir, d, "analyzers.done")):
                t = self.load_image_report(d)
                ret[d] = list(set(t['anchore_all_tags']) | set(t['anchore_current_tags']))
        return(ret)

    def load_all_images(self):
        ret = {}
        
        for d in os.listdir(self.imagerootdir):
            try:
                result = self.load_image(d)
                if result['meta']['imageId'] not in ret:
                    ret[result['meta']['imageId']] = result
            except Exception as err:
                pass
            
        return(ret)

    def load_all_images_iter(self):
        for d in os.listdir(self.imagerootdir):
            try:
                result = self.load_image(d)
                r = (result['meta']['imageId'], result)
                yield r
            except Exception as err:
                pass

    def delete_image(self, imageId):
        imagedir = '/'.join([self.imagerootdir, imageId])
        if os.path.exists(imagedir):
            shutil.rmtree(imagedir)
            
    def load_image(self, imageId):
        return(self.load_image_report(imageId));

    def load_image_new(self, imageId):
        ret = {}

        ret['image_report'] = self.load_image_report(imageId)
        ret['analysis_report'] = self.load_analysis_report(imageId)
        ret['analyzer_manifest'] = self.load_analyzer_manifest(imageId)
        ret['gates_report'] = self.load_gates_report(imageId)
        ret['gates_eval_report'] = self.load_gates_eval_report(imageId)

        return(ret)

    def create_image(self, imageId):
        return(self.make_image_structure(imageId))

    def make_image_structure(self, imageId):
        imgdir = os.path.join(self.imagerootdir, imageId)
        subdirs = ['analyzer_output', 'analyzer_output_extra', 'analyzer_output_user', 'gates_output', 'image_output', 'reports']
        
        if not os.path.exists(imgdir):
            os.makedirs(imgdir)

        for d in subdirs:
            if not os.path.exists(os.path.join(imgdir, d)):
                os.makedirs(os.path.join(imgdir, d))
        return(True)

    def save_image_new(self, imageId, report=None):
        # setup dir structure
        self.make_image_structure(imageId)

        if not report:
            report = load_image_new(imageId)

        # store the reports
        self.save_image_report(imageId, report['image_report'])
        self.save_analysis_report(imageId, report['analysis_report'])
        self.save_analyzer_manifest(imageId, report['analyzer_manifest'])
        self.save_gates_report(imageId, report['gates_report'])
        self.save_gates_eval_report(imageId, report['gates_eval_report'])

        # populate the analyzer_outputs
        for module_name in report['analysis_report'].keys():
            for module_value in report['analysis_report'][module_name].keys():
                for module_type in ['base', 'extra', 'user']:
                    if module_type in report['analysis_report'][module_name][module_value]:
                        adata = report['analysis_report'][module_name][module_value][module_type]
                        if adata:
                            self.save_analysis_output(imageId, module_name, module_value, adata, module_type=module_type)
                            
        # populate gates outputs
        for gname in report['gates_report'].keys():
            self.save_gate_output(imageId, gname, report['gates_report'][gname])

        # populate image metadata
        thedir = os.path.join(self.imagerootdir, imageId, "image_output", "image_info")
        if not os.path.exists(thedir):
            os.makedirs(thedir)

        thefile = os.path.join(thedir, "image.meta")
        anchore_utils.write_kvfile_fromdict(thefile, report['image_report']['meta'])

        thefile = os.path.join(thedir, "Dockerfile")
        anchore_utils.write_plainfile_fromstr(thefile, report['image_report']['dockerfile_contents'])

        return(True)
                

    def load_analysis_report(self, imageId):
        thefile = self.imagerootdir + "/" + imageId + "/reports/analysis_report.json"
        if not os.path.exists(thefile):
            return({})

        FH = open(thefile, 'r')
        ret = json.loads(FH.read())
        FH.close()
        return(ret)

    def save_analysis_report(self, imageId, report):
        thedir = self.imagerootdir + "/" + imageId + "/reports/"
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = thedir + "/analysis_report.json"
        anchore_utils.update_file_jsonstr(json.dumps(report), thefile, False)

    def list_analysis_outputs(self, imageId):
        aret = {}
        amanifest = self.load_analyzer_manifest(imageId)
        for a in amanifest.keys():
            if 'analyzer_outputs' in amanifest[a]:
                for record in amanifest[a]['analyzer_outputs']:
                    module_name = record['module_name']
                    module_value = record['module_value']
                    if module_name not in aret:
                        aret[module_name] = {}
                    aret[module_name][module_value] = True
        return(aret)

    def load_analyzer_manifest(self, imageId):
        ret = {}
        thefile = os.path.join(self.imagerootdir, imageId, 'analyzers.done')
        if os.path.exists(thefile):
            with open(thefile, 'r') as FH:
                try:
                    ret = json.loads(FH.read())
                except:
                    ret = {}
        return(ret)

    def save_analyzer_manifest(self, imageId, data):
        thefile = os.path.join(self.imagerootdir, imageId, 'analyzers.done')
        if data:
            with open(thefile, 'w') as FH:
                FH.write(json.dumps(data))

    def load_analysis_output(self, imageId, module_name, module_value, module_type=None):
        ret = {}

        if not module_type or module_type == 'base':
            thefile = '/'.join([self.imagerootdir, imageId, "analyzer_output", module_name, module_value])
        else:
            thefile = '/'.join([self.imagerootdir, imageId, "analyzer_output_"+module_type, module_name, module_value])

        if os.path.exists(thefile):
            if os.path.isfile(thefile):
                ret = anchore_utils.read_kvfile_todict(thefile)
            elif os.path.isdir(thefile):
                ret = thefile
                import tarfile, io
                try:
                    TFH = io.BytesIO()
                    tar = tarfile.open(fileobj=TFH, mode='w:gz', format=tarfile.PAX_FORMAT)
                    for l in os.listdir(thefile):
                        tarfile = os.path.join(thefile, l)
                        tar.add(tarfile)
                    tar.close()
                    TFH.seek(0)
                    ret = TFH
                except Exception as err:
                    import traceback
                    traceback.print_exc()
                    print str(err)

        return(ret)

    def save_analysis_output(self, imageId, module_name, module_value, data, module_type=None, directory_data=False):
        if not module_type or module_type == 'base':
            odir = '/'.join([self.imagerootdir, imageId, "analyzer_output", module_name])
        else:
            odir = '/'.join([self.imagerootdir, imageId, "analyzer_output_"+module_type, module_name])

        if not directory_data:
            thefile = '/'.join([odir, module_value])
            if not os.path.exists(odir):
                os.makedirs(odir)

            return(anchore_utils.write_kvfile_fromdict(thefile, data))
        else:
            if os.path.isdir(data):
                if os.path.isdir(odir):
                    shutil.rmtree(odir)
                os.makedirs(odir)
                shutil.move(data, odir)

    def load_gates_report(self, imageId):
        thefile = self.imagerootdir + "/" + imageId + "/reports/gates_report.json"
        if not os.path.exists(thefile):
            return({})

        FH = open(thefile, 'r')
        ret = json.loads(FH.read())
        FH.close()
        return(ret)

    def save_gates_report(self, imageId, report):
        thedir = self.imagerootdir + "/" + imageId + "/reports/"
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = thedir + "/gates_report.json"
        anchore_utils.update_file_jsonstr(json.dumps(report), thefile, False)

    
    def load_gate_output(self, imageId, gate_name):
        thedir = os.path.join(self.imagerootdir, imageId, 'gates_output')
        thefile = os.path.join(thedir, gate_name)
        return(anchore_utils.read_plainfile_tolist(thefile))

    def list_gate_outputs(self, imageId):
        ret = list()
        thedir = os.path.join(self.imagerootdir, imageId, 'gates_output')
        if not os.path.exists(thedir):
            return(ret)
        for d in os.listdir(thedir):
            if re.match(".*\.eval$", d) or re.match(".*\.help$", d):
                continue

            if d not in ret:
                ret.append(d)
        return(ret)

    def save_gate_output(self, imageId, gate_name, data):
        thedir = os.path.join(self.imagerootdir, imageId, 'gates_output')
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = os.path.join(thedir, gate_name)
        return(anchore_utils.write_plainfile_fromlist(thefile, data))

    def save_gate_help_output(self, gate_help):
        thedir = os.path.join(self.imagerootdir)
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = os.path.join(thedir, "gates_info.json")
        rc = anchore_utils.update_file_jsonstr(json.dumps(gate_help), thefile)
        return(rc)

    def save_gate_eval_output(self, imageId, gate_name, data):
        thedir = os.path.join(self.imagerootdir, imageId, "gates_output")
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = os.path.join(thedir, gate_name+".eval")
        return(anchore_utils.write_plainfile_fromlist(thefile, data))

    def del_gate_eval_output(self, imageId, gate_name):
        thefile = os.path.join(self.imagerootdir, imageId, "gates_output", imageId, gate_name)
        if os.path.exists(thefile):
            try:
                os.remove(thefile)
            except:
                pass
        return(True)

    def load_gates_eval_report(self, imageId):
        thefile = self.imagerootdir + "/" + imageId + "/reports/gates_eval_report.json"
        if not os.path.exists(thefile):
            return({})

        FH = open(thefile, 'r')
        ret = json.loads(FH.read())
        FH.close()
        return(ret)

    def save_gates_eval_report(self, imageId, report):
        thedir = self.imagerootdir + "/" + imageId + "/reports/"
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = thedir + "/gates_eval_report.json"
        anchore_utils.update_file_jsonstr(json.dumps(report), thefile, False)

    def load_gate_policy(self, imageId):
        thefile = os.path.join(self.imagerootdir, imageId, 'anchore_gate.policy')
        return(anchore_utils.read_plainfile_tolist(thefile))

    def save_gate_policy(self, imageId, data):
        thedir = os.path.join(self.imagerootdir, imageId)
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = os.path.join(thedir, "anchore_gate.policy")
        return(anchore_utils.write_plainfile_fromlist(thefile, data))

    def del_gate_policy(self, imageId):
        thefile = os.path.join(self.imagerootdir, imageId, 'anchore_gate.policy')
        try:
            os.remove(thefile)
        except:
            pass
        return(True)

    def load_gate_whitelist(self, imageId):
        thefile = os.path.join(self.imagerootdir, imageId, 'anchore_gate.whitelist')
        return(anchore_utils.read_plainfile_tolist(thefile))

    def save_gate_whitelist(self, imageId, data):
        thedir = os.path.join(self.imagerootdir, imageId)
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = os.path.join(thedir, 'anchore_gate.whitelist')
        return(anchore_utils.write_plainfile_fromlist(thefile, data))

    def load_image_report(self, imageId):
        thefile = self.imagerootdir + "/" + imageId + "/reports/image_report.json"
        if not os.path.exists(thefile):
            return({})

        ret = {}
        try:
            with open(thefile, 'r') as FH:
                ret = json.loads(FH.read())
        except Exception as err:
            self._logger.debug("image report json found ("+str(thefile)+"), but failed to load for imageId ("+str(imageId)+") - exception: " + str(err))
            ret = {}

        return(ret)

    def save_image_report(self, imageId, report):
        # populate image metadata
        thedir = os.path.join(self.imagerootdir, imageId, "image_output", "image_info")
        if not os.path.exists(thedir):
            os.makedirs(thedir)

        thefile = os.path.join(thedir, "image.meta")
        if 'meta' in report:
            anchore_utils.write_kvfile_fromdict(thefile, report['meta'])

        # save the report itself
        date = str(int(time.time()))
        thedir = self.imagerootdir + "/" + imageId + "/reports/"
        if not os.path.exists(thedir):
            os.makedirs(thedir)
        thefile = thedir + "/image_report.json"

        if os.path.exists(thefile):
            oldreport = self.load_image_report(imageId)
            if 'tag_history' in oldreport:
                report['tag_history'] = list(oldreport['tag_history'])
            else:
                report['tag_history'] = list()

            if 'anchore_current_tags' not in oldreport:
                oldreport['anchore_current_tags'] = list([date, report['anchore_current_tags']])

            diff = list(set(oldreport['anchore_current_tags']).symmetric_difference(set(report['anchore_current_tags'])))
            if len(diff) > 0:
                # there is a difference between stored tags and new tags
                report['tag_history'].append([date, oldreport['anchore_current_tags']])
        
        if 'tag_history' not in report:
            report['tag_history'] = list()

        if len(report['tag_history']) <= 0:
            report['tag_history'].append([date, report['anchore_current_tags']])

        anchore_utils.update_file_jsonstr(json.dumps(report), thefile, False)
