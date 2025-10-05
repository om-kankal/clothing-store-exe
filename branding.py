
class the_one:
    def __init__(self,bname,name):
        self.bname=bname
        self.name=name

    def branding(self):
        print("the ",self.name,"is from ",self.bname,"company")

name1=input("enter brand name of car :-")
name2=input("enter name of car :-")

one=the_one(name1,name2)

one.branding()