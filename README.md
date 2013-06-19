## Description

The fcc-textify package is a set of tools to make the contents of FCC PDF
comments searchable by creating a parallel database of comment filings
in which the text of comment documents have been extracted and indexed.

There are two modes of operation:

When the system is first initialized, all comments are
bootstrapped into the database.

Subsequent updates then need to be as new comments are added to the FCC database.

Bootstrapping:

  1. Setup a set of EC2 processing nodes and start them. See instructions below.

  2. Run the injector script to feed data into the processing nodes 
   
      sh run-task auth/production/injector.key inject

  3. Run the collector script to update the database with the results.

      sh run-task auth/production/collector.key collect

  Note: All three sets of scripts run simultaneously.

  Be sure to stop the EC2 instances when done.
     
Maintenance mode:

Invoke 
    
  sh run

Once a day to fetch and process new comments for all currently open proceedings.

## Setting up EC2 nodes for bootstrapping or ongoing extraction

Users:

The infrastructure requires three types of AWS users:

injectors - add new jobs to queue
workers - perform text extraction
collectors - update database with extraction results

To allow for simpler management, each category of users belongs
to an eponymous group. To allow for separate development and production
roles, there are two sets of each group, with names suffixed by role.

1. Create groups

    iam-groupcreate injectors-production
    iam-groupcreate workers-production
    iam-groupcreate collectors-production

2. Create users for each group

    iam-usercreate -u injector-production-0
    iam-usercreate -u worker-production-0
    iam-usercreate -u collector-production-0

3. Add users to appropriate groups 

    iam-groupadduser -g collectors-production -u collector-production-0
    iam-groupadduser -g injectors-production -u injector-production-0
    iam-groupadduser -g workers-production -u worker-production-0

4. Generate keys for each user

    #in fcc-textify directory
    mkdir -p auth/production

    iam-useraddkey -u injector-production-0 >  auth/production/injector.key
    iam-useraddkey -u worker-production-0 >  auth/production/worker.key
    iam-useraddkey -u collector-production-0 >  auth/production/collector.key

5. Define access policies for each role

   iam-groupuploadpolicy -g injectors-production -p injectors-production-access -f policies/production/injector.json
   iam-groupuploadpolicy -g workers-production -p workers-production-access -f policies/production/worker.json   
   iam-groupuploadpolicy -g collectors-production -p collectors-production-access -f policies/production/collector.json

# Nodes

Text extraction requires one or more worker nodes, depending on the number of files to be converted.
The approach taken here is to define a template instance from which all workers are run. This
method leads to faster and more reliable startups. There is a small added cost for storing
the template, but this can be avoided by deleting the template at the end of each run and
recreating it anew when necessary. Since the process is automated, this is not much of a problem.

1. Create an ssh key pair for managing nodes. If you already have a pair, skip this step.

    # Key name
    KEY=$USER@ec2

    ssh-keygen -t rsa -b 2048 -C $KEY -f .ssh/$USER@ec2

2. Register public key

    ec2-import-keypair $KEY --public-key-file .ssh/${KEY}.pub

3. Create a template image

   AMI=ami-f3d1bb9a
   # Ubuntu 13.04 64 bit ebs

   USERDATA=ec2-initialize
   # you have to write this script,
   # which customizes the instance however you need.
   # See example in repository.
                            
   create-template-image $AMI $KEY $USERDATA 

4. Run an instances based on the template image

    use ec2-describe-images to find the newly created image
    and run an instance:

    #pick appropriate size
    TYPE=t1.micro

    ec2-run-instances $AMI -k $KEY -t $TYPE 

5 Connect to the instance

    ssh ubuntu@instance-public-dns

Addenda:

    a. You'll need to allow ssh access to your instances
    b. You'll need to use ec2-describe-instances or other tool to find the public hostname

## Misc Notes

  Some useful commands.

  # initialize a template host
  ec2-run-instances ami-f3d1bb9a -k gyepi@ec2 -t t1.micro  -f ec2-initialize-production

  # create an image based on the template host
  ec2-create-template-image $INSTANCEID

  # run a bunch of spot instances (15 by default)
  ./run-spot-instances $IMAGEID $KEY

  # make a list of cluster hosts
  aws ec2 describe-instances | jq -M -r '.Reservations[].Instances[].PublicDnsName') > cluster

  export CLUSTER=$PWD/cluster

  # list processes on each node
  dsh -l ubuntu -g web 'ps ax' | tee /tmp/ps.log


  # get the last 10 log entries on each node
  dsh -l ubuntu 'tail /var/log/syslog' | tee /tmp/syslog.log


  # tail instance logs - can't use dsh here
  cat cluster | parallel -u ssh {} tail -f /var/log/syslog
